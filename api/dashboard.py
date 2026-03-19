"""
Finance Trade API — 경량 대시보드 (FastAPI + 인라인 HTML)

실행 방법:
    python -m api.dashboard
    또는
    uvicorn api.dashboard:app --reload --port 8000

접속: http://localhost:8000
"""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (단독 실행 시)
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db.models  # noqa: F401  — 모든 모델 등록
from config import get_settings
from db.models.balance import BalanceHistoryModel
from db.models.order import OrderModel
from db.models.position import PositionModel
from db.models.signal import SignalModel
from strategy.store import strategy_store

app = FastAPI(title="Finance Trade Dashboard", docs_url="/api/docs")

# ── DB 세션 (대시보드 전용 read-only 연결) ───────────────────────────────────

_engine = None
_session_factory = None


def _get_engine():
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.db_url, echo=False)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine, _session_factory


# ── HTML 템플릿 헬퍼 ─────────────────────────────────────────────────────────

_HTML_BASE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Finance Trade Dashboard</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body {{ background: #0d1117; color: #c9d1d9; font-family: 'Courier New', monospace; }}
    .navbar {{ background: #161b22 !important; border-bottom: 1px solid #30363d; }}
    .card {{ background: #161b22; border: 1px solid #30363d; }}
    .card-header {{ background: #21262d; border-bottom: 1px solid #30363d; font-weight: bold; }}
    .table {{ color: #c9d1d9; }}
    .table td, .table th {{ border-color: #30363d; }}
    .badge-buy  {{ background: #1f6feb; }}
    .badge-sell {{ background: #da3633; }}
    .badge-hold {{ background: #3d444d; }}
    .pnl-pos {{ color: #3fb950; }}
    .pnl-neg {{ color: #f85149; }}
    .stat-card {{ background: #21262d; border-radius: 8px; padding: 16px; text-align: center; }}
    .stat-value {{ font-size: 1.6rem; font-weight: bold; }}
    a.nav-link {{ color: #8b949e !important; }}
    a.nav-link:hover, a.nav-link.active {{ color: #58a6ff !important; }}
    .refresh-btn {{ font-size: 0.8rem; }}
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark">
  <div class="container-fluid">
    <span class="navbar-brand text-warning fw-bold">⚡ Finance Trade Dashboard</span>
    <div class="navbar-nav ms-3">
      <a class="nav-link {nav_overview}" href="/">Overview</a>
      <a class="nav-link {nav_positions}" href="/positions">Positions</a>
      <a class="nav-link {nav_orders}" href="/orders">Orders</a>
      <a class="nav-link {nav_signals}" href="/signals">Signals</a>
      <a class="nav-link {nav_balances}" href="/balances">Balances</a>
      <a class="nav-link {nav_strategies}" href="/strategies">Strategies</a>
      <a class="nav-link {nav_backtest}" href="/backtest">Backtest</a>
    </div>
    <span class="text-muted ms-auto refresh-btn">
      <a href="{current_url}" class="text-secondary text-decoration-none">↻ 새로고침</a>
      &nbsp;|&nbsp; {now}
    </span>
  </div>
</nav>
<div class="container-fluid py-3">
{body}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""


def _render(body: str, active: str, current_url: str = "/") -> HTMLResponse:
    nav = {f"nav_{k}": "" for k in ["overview", "positions", "orders", "signals", "balances", "strategies", "backtest"]}
    nav[f"nav_{active}"] = "active"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = _HTML_BASE.format(body=body, current_url=current_url, now=now, **nav)
    return HTMLResponse(html)


def _pnl_class(val) -> str:
    try:
        return "pnl-pos" if float(val) >= 0 else "pnl-neg"
    except Exception:
        return ""


def _fmt(val, decimals: int = 2) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):,.{decimals}f}"
    except Exception:
        return str(val)


# ── Overview ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    _, sf = _get_engine()
    async with sf() as session:
        # 총 주문 수
        total_orders = (await session.execute(text("SELECT COUNT(*) FROM orders"))).scalar() or 0
        # 오늘 신호 수
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total_signals = (
            await session.execute(
                text("SELECT COUNT(*) FROM signals WHERE created_at >= :d"),
                {"d": today},
            )
        ).scalar() or 0
        # 오픈 포지션 수 (최신 심볼별)
        open_pos = (
            await session.execute(
                text("""
                    SELECT COUNT(DISTINCT symbol) FROM (
                        SELECT symbol, current_qty,
                               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY recorded_at DESC) rn
                        FROM positions
                    ) WHERE rn=1 AND current_qty > 0
                """)
            )
        ).scalar() or 0
        # 최근 KRW 잔고
        krw_row = (
            await session.execute(
                text("SELECT balance FROM balance_history WHERE currency='KRW' ORDER BY recorded_at DESC LIMIT 1")
            )
        ).fetchone()
        krw_balance = krw_row[0] if krw_row else None

        # 최근 주문 5건
        recent_orders = (
            await session.execute(
                select(OrderModel).order_by(desc(OrderModel.created_at)).limit(5)
            )
        ).scalars().all()

        # 최근 신호 5건
        recent_signals = (
            await session.execute(
                select(SignalModel).order_by(desc(SignalModel.created_at)).limit(5)
            )
        ).scalars().all()

    # ── 통계 카드 ─────────────────────────────────────────────────────────────
    stats = f"""
    <div class="row g-3 mb-4">
      <div class="col-6 col-md-3">
        <div class="stat-card">
          <div class="text-muted small">총 주문</div>
          <div class="stat-value text-info">{total_orders}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card">
          <div class="text-muted small">오늘 시그널</div>
          <div class="stat-value text-warning">{total_signals}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card">
          <div class="text-muted small">오픈 포지션</div>
          <div class="stat-value text-success">{open_pos}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card">
          <div class="text-muted small">KRW 잔고</div>
          <div class="stat-value text-light">{_fmt(krw_balance, 0) if krw_balance else '—'}</div>
        </div>
      </div>
    </div>"""

    # ── 최근 주문 테이블 ──────────────────────────────────────────────────────
    order_rows = "".join(
        f"""<tr>
          <td>{o.symbol}</td>
          <td><span class="badge {'badge-buy' if o.side=='buy' else 'badge-sell'}">{o.side.upper()}</span></td>
          <td>{_fmt(o.executed_qty, 6)}</td>
          <td>{_fmt(o.executed_price, 0)}</td>
          <td><span class="badge bg-secondary">{o.status}</span></td>
          <td class="text-muted small">{o.created_at.strftime('%m-%d %H:%M') if o.created_at else '—'}</td>
        </tr>"""
        for o in recent_orders
    ) or "<tr><td colspan='6' class='text-center text-muted'>데이터 없음</td></tr>"

    # ── 최근 시그널 테이블 ────────────────────────────────────────────────────
    signal_rows = "".join(
        f"""<tr>
          <td>{s.symbol}</td>
          <td><span class="badge {'badge-buy' if s.signal_type=='buy' else ('badge-sell' if s.signal_type=='sell' else 'badge-hold')}">{s.signal_type.upper()}</span></td>
          <td>{s.strategy_name}</td>
          <td>{_fmt(s.strength, 2)}</td>
          <td class="text-muted small">{s.created_at.strftime('%m-%d %H:%M') if s.created_at else '—'}</td>
        </tr>"""
        for s in recent_signals
    ) or "<tr><td colspan='5' class='text-center text-muted'>데이터 없음</td></tr>"

    body = stats + f"""
    <div class="row g-3">
      <div class="col-md-6">
        <div class="card">
          <div class="card-header">📋 최근 주문 <a href="/orders" class="float-end text-secondary text-decoration-none small">전체 보기 →</a></div>
          <div class="card-body p-0">
            <table class="table table-sm table-hover mb-0">
              <thead><tr><th>심볼</th><th>방향</th><th>체결수량</th><th>체결가</th><th>상태</th><th>시간</th></tr></thead>
              <tbody>{order_rows}</tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="card">
          <div class="card-header">📡 최근 시그널 <a href="/signals" class="float-end text-secondary text-decoration-none small">전체 보기 →</a></div>
          <div class="card-body p-0">
            <table class="table table-sm table-hover mb-0">
              <thead><tr><th>심볼</th><th>타입</th><th>전략</th><th>강도</th><th>시간</th></tr></thead>
              <tbody>{signal_rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>"""

    return _render(body, "overview", "/")


# ── Positions ────────────────────────────────────────────────────────────────

@app.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request):
    _, sf = _get_engine()
    async with sf() as session:
        # 심볼별 최신 포지션만
        rows = (
            await session.execute(
                text("""
                    SELECT symbol, side, quantity, avg_price, current_qty, unrealized_pnl, recorded_at
                    FROM positions
                    WHERE (symbol, recorded_at) IN (
                        SELECT symbol, MAX(recorded_at) FROM positions GROUP BY symbol
                    )
                    ORDER BY recorded_at DESC
                """)
            )
        ).fetchall()

    table_rows = "".join(
        f"""<tr>
          <td class="fw-bold">{r[0]}</td>
          <td><span class="badge {'badge-buy' if r[1]=='buy' else 'badge-sell'}">{r[1].upper()}</span></td>
          <td>{_fmt(r[4], 6)}</td>
          <td>{_fmt(r[3], 0)}</td>
          <td class="{_pnl_class(r[5])}">{_fmt(r[5], 0)}</td>
          <td class="text-muted small">{r[6].strftime('%Y-%m-%d %H:%M') if r[6] else '—'}</td>
        </tr>"""
        for r in rows
    ) or "<tr><td colspan='6' class='text-center text-muted py-3'>보유 포지션 없음</td></tr>"

    body = f"""
    <div class="card">
      <div class="card-header">📊 포지션 현황 (심볼별 최신)</div>
      <div class="card-body p-0">
        <table class="table table-hover mb-0">
          <thead><tr><th>심볼</th><th>방향</th><th>보유수량</th><th>평균단가</th><th>미실현손익</th><th>업데이트</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
      </div>
    </div>"""

    return _render(body, "positions", "/positions")


# ── Orders ───────────────────────────────────────────────────────────────────

@app.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    _, sf = _get_engine()
    async with sf() as session:
        orders = (
            await session.execute(
                select(OrderModel).order_by(desc(OrderModel.created_at)).limit(50)
            )
        ).scalars().all()

    rows = "".join(
        f"""<tr>
          <td class="text-muted small">{o.order_id[:16]}…</td>
          <td>{o.symbol}</td>
          <td><span class="badge {'badge-buy' if o.side=='buy' else 'badge-sell'}">{o.side.upper()}</span></td>
          <td>{o.order_type}</td>
          <td>{_fmt(o.quantity, 6)}</td>
          <td>{_fmt(o.executed_qty, 6)}</td>
          <td>{_fmt(o.executed_price, 0)}</td>
          <td><span class="badge bg-{'success' if o.status=='done' else ('danger' if o.status=='failed' else 'secondary')}">{o.status}</span></td>
          <td class="text-muted small">{o.strategy_name or '—'}</td>
          <td class="text-muted small">{o.created_at.strftime('%m-%d %H:%M') if o.created_at else '—'}</td>
        </tr>"""
        for o in orders
    ) or "<tr><td colspan='10' class='text-center text-muted py-3'>주문 없음</td></tr>"

    body = f"""
    <div class="card">
      <div class="card-header">📋 주문 내역 (최근 50건)</div>
      <div class="card-body p-0" style="overflow-x:auto">
        <table class="table table-sm table-hover mb-0">
          <thead><tr><th>주문ID</th><th>심볼</th><th>방향</th><th>유형</th><th>주문수량</th><th>체결수량</th><th>체결가</th><th>상태</th><th>전략</th><th>시간</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""

    return _render(body, "orders", "/orders")


# ── Signals ──────────────────────────────────────────────────────────────────

@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request):
    _, sf = _get_engine()
    async with sf() as session:
        signals = (
            await session.execute(
                select(SignalModel).order_by(desc(SignalModel.created_at)).limit(50)
            )
        ).scalars().all()

    rows = "".join(
        f"""<tr>
          <td>{s.symbol}</td>
          <td><span class="badge {'badge-buy' if s.signal_type=='buy' else ('badge-sell' if s.signal_type=='sell' else 'badge-hold')}">{s.signal_type.upper()}</span></td>
          <td>{s.strategy_name}</td>
          <td>{'▓' * int(min(s.strength * 10, 10))} {_fmt(s.strength, 2)}</td>
          <td class="text-muted small">{s.created_at.strftime('%Y-%m-%d %H:%M:%S') if s.created_at else '—'}</td>
        </tr>"""
        for s in signals
    ) or "<tr><td colspan='5' class='text-center text-muted py-3'>시그널 없음</td></tr>"

    body = f"""
    <div class="card">
      <div class="card-header">📡 시그널 이력 (최근 50건)</div>
      <div class="card-body p-0">
        <table class="table table-sm table-hover mb-0">
          <thead><tr><th>심볼</th><th>타입</th><th>전략</th><th>강도</th><th>생성시간</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""

    return _render(body, "signals", "/signals")


# ── Balances ─────────────────────────────────────────────────────────────────

@app.get("/balances", response_class=HTMLResponse)
async def balances_page(request: Request):
    _, sf = _get_engine()
    async with sf() as session:
        # 통화별 최신 잔고
        latest = (
            await session.execute(
                text("""
                    SELECT currency, balance, recorded_at
                    FROM balance_history
                    WHERE (currency, recorded_at) IN (
                        SELECT currency, MAX(recorded_at) FROM balance_history GROUP BY currency
                    )
                    ORDER BY currency
                """)
            )
        ).fetchall()

        # 잔고 이력 (최근 20건)
        history = (
            await session.execute(
                select(BalanceHistoryModel)
                .order_by(desc(BalanceHistoryModel.recorded_at))
                .limit(20)
            )
        ).scalars().all()

    latest_rows = "".join(
        f"""<tr>
          <td class="fw-bold">{r[0]}</td>
          <td>{_fmt(r[1], 8 if r[0] != 'KRW' else 0)}</td>
          <td class="text-muted small">{r[2].strftime('%Y-%m-%d %H:%M') if r[2] else '—'}</td>
        </tr>"""
        for r in latest
    ) or "<tr><td colspan='3' class='text-center text-muted py-3'>잔고 없음</td></tr>"

    history_rows = "".join(
        f"""<tr>
          <td>{h.currency}</td>
          <td>{_fmt(h.balance, 8 if h.currency != 'KRW' else 0)}</td>
          <td class="text-muted small">{h.recorded_at.strftime('%Y-%m-%d %H:%M:%S') if h.recorded_at else '—'}</td>
        </tr>"""
        for h in history
    ) or "<tr><td colspan='3' class='text-center text-muted py-3'>이력 없음</td></tr>"

    body = f"""
    <div class="row g-3">
      <div class="col-md-4">
        <div class="card">
          <div class="card-header">💰 현재 잔고</div>
          <div class="card-body p-0">
            <table class="table table-sm table-hover mb-0">
              <thead><tr><th>통화</th><th>잔고</th><th>업데이트</th></tr></thead>
              <tbody>{latest_rows}</tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="col-md-8">
        <div class="card">
          <div class="card-header">📈 잔고 이력 (최근 20건)</div>
          <div class="card-body p-0">
            <table class="table table-sm table-hover mb-0">
              <thead><tr><th>통화</th><th>잔고</th><th>기록시간</th></tr></thead>
              <tbody>{history_rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>"""

    return _render(body, "balances", "/balances")


# ── Strategies ───────────────────────────────────────────────────────────────

@app.get("/strategies", response_class=HTMLResponse)
async def strategies_page(request: Request):
    strategies = strategy_store.to_dict_list()

    if not strategies:
        body = """
        <div class="alert alert-warning">
          등록된 전략이 없습니다. 트레이딩 엔진과 같은 프로세스로 실행해야 전략이 표시됩니다.
        </div>"""
        return _render(body, "strategies", "/strategies")

    cards = ""
    for s in strategies:
        param_rows = ""
        schema = s.get("param_schema", {})
        for k, v in s["params"].items():
            sc = schema.get(k, {})
            desc = sc.get("description", "")
            type_badge = f'<span class="badge bg-secondary">{sc.get("type", "?")}</span>'
            param_rows += f"""
            <tr>
              <td class="fw-bold">{k}</td>
              <td>{type_badge}</td>
              <td><input class="form-control form-control-sm param-input bg-dark text-light border-secondary"
                         style="width:120px"
                         data-strategy="{s['name']}" data-key="{k}"
                         value="{v}" type="{'number' if isinstance(v, (int, float)) else 'text'}"></td>
              <td class="text-muted small">{desc}</td>
            </tr>"""

        symbol_badges = " ".join(f'<span class="badge bg-info text-dark">{sym}</span>' for sym in s["symbols"])
        cards += f"""
        <div class="col-md-6 col-xl-4">
          <div class="card h-100">
            <div class="card-header d-flex justify-content-between align-items-center">
              <span>⚙️ {s['name']}</span>
              <span class="badge bg-primary">{s['class']}</span>
            </div>
            <div class="card-body">
              <div class="mb-2">심볼: {symbol_badges}</div>
              <table class="table table-sm mb-2">
                <thead><tr><th>파라미터</th><th>타입</th><th>현재값</th><th>설명</th></tr></thead>
                <tbody>{param_rows}</tbody>
              </table>
              <button class="btn btn-sm btn-success w-100 apply-btn" data-strategy="{s['name']}">
                ✓ 적용 (실시간 반영)
              </button>
              <div class="apply-result mt-1 small"></div>
            </div>
          </div>
        </div>"""

    body = f"""
    <div class="row g-3 mb-3">
      <div class="col-12">
        <div class="alert alert-info py-2 mb-0">
          파라미터 수정 후 <strong>적용</strong> 버튼을 누르면 트레이딩 엔진에 즉시 반영됩니다. 재시작 불필요.
        </div>
      </div>
    </div>
    <div class="row g-3">{cards}</div>
    <script>
    document.querySelectorAll('.apply-btn').forEach(btn => {{
      btn.addEventListener('click', async () => {{
        const name = btn.dataset.strategy;
        const inputs = document.querySelectorAll(`.param-input[data-strategy="${{name}}"]`);
        const params = {{}};
        inputs.forEach(inp => {{
          const v = inp.value;
          params[inp.dataset.key] = isNaN(v) ? v : (v.includes('.') ? parseFloat(v) : parseInt(v));
        }});
        const res = await fetch(`/api/strategies/${{name}}/params`, {{
          method: 'PUT',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{params}})
        }});
        const result = btn.closest('.card').querySelector('.apply-result');
        if (res.ok) {{
          result.innerHTML = '<span class="text-success">✓ 적용 완료</span>';
        }} else {{
          result.innerHTML = '<span class="text-danger">✗ 실패: ' + (await res.text()) + '</span>';
        }}
        setTimeout(() => result.innerHTML = '', 3000);
      }});
    }});
    </script>"""

    return _render(body, "strategies", "/strategies")


# ── JSON API ─────────────────────────────────────────────────────────────────

@app.get("/api/strategies")
async def api_strategies():
    return strategy_store.to_dict_list()


@app.put("/api/strategies/{name}/params")
async def api_update_strategy_params(name: str, body: dict):
    """전략 파라미터 실시간 갱신."""
    new_params: dict = body.get("params", {})
    if not new_params:
        return JSONResponse({"error": "params 필드가 비어 있습니다."}, status_code=400)
    ok = strategy_store.update_params(name, new_params)
    if not ok:
        return JSONResponse(
            {"error": f"'{name}' 전략을 찾을 수 없습니다. (엔진 미실행 또는 등록 안 됨)"},
            status_code=404,
        )
    return {"strategy": name, "updated_params": new_params}


@app.get("/api/positions")
async def api_positions():
    _, sf = _get_engine()
    async with sf() as session:
        rows = (
            await session.execute(
                text("""
                    SELECT symbol, side, current_qty, avg_price, unrealized_pnl, recorded_at
                    FROM positions
                    WHERE (symbol, recorded_at) IN (
                        SELECT symbol, MAX(recorded_at) FROM positions GROUP BY symbol
                    )
                """)
            )
        ).fetchall()
    return [
        {"symbol": r[0], "side": r[1], "qty": str(r[2]),
         "avg_price": str(r[3]), "unrealized_pnl": str(r[4])}
        for r in rows
    ]


@app.get("/api/orders")
async def api_orders(limit: int = 20):
    _, sf = _get_engine()
    async with sf() as session:
        orders = (
            await session.execute(
                select(OrderModel).order_by(desc(OrderModel.created_at)).limit(limit)
            )
        ).scalars().all()
    return [
        {"order_id": o.order_id, "symbol": o.symbol, "side": o.side,
         "status": o.status, "qty": str(o.executed_qty),
         "price": str(o.executed_price), "created_at": str(o.created_at)}
        for o in orders
    ]


@app.get("/api/signals")
async def api_signals(limit: int = 20):
    _, sf = _get_engine()
    async with sf() as session:
        signals = (
            await session.execute(
                select(SignalModel).order_by(desc(SignalModel.created_at)).limit(limit)
            )
        ).scalars().all()
    return [
        {"symbol": s.symbol, "type": s.signal_type, "strategy": s.strategy_name,
         "strength": s.strength, "created_at": str(s.created_at)}
        for s in signals
    ]


# ── Backtest ─────────────────────────────────────────────────────────────────

@app.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    """백테스트 실행 폼 + 결과 시각화."""
    form_html = """
    <div class="card mb-4">
      <div class="card-header">🔬 백테스트 실행</div>
      <div class="card-body">
        <form id="bt-form" class="row g-2">
          <div class="col-md-2">
            <label class="form-label small text-muted">전략</label>
            <select class="form-select form-select-sm bg-dark text-light border-secondary" name="strategy">
              <option value="ma_crossover">MA Crossover</option>
              <option value="rsi">RSI</option>
              <option value="bollinger">Bollinger</option>
              <option value="macd">MACD</option>
            </select>
          </div>
          <div class="col-md-2">
            <label class="form-label small text-muted">심볼</label>
            <input class="form-control form-control-sm bg-dark text-light border-secondary" name="symbol" value="KRW-BTC">
          </div>
          <div class="col-md-2">
            <label class="form-label small text-muted">캔들 수</label>
            <input class="form-control form-control-sm bg-dark text-light border-secondary" name="n_candles" type="number" value="120" min="50">
          </div>
          <div class="col-md-2">
            <label class="form-label small text-muted">초기 자본 (KRW)</label>
            <input class="form-control form-control-sm bg-dark text-light border-secondary" name="initial_balance" type="number" value="1000000">
          </div>
          <div class="col-md-2">
            <label class="form-label small text-muted">short_window</label>
            <input class="form-control form-control-sm bg-dark text-light border-secondary" name="short_window" type="number" value="5">
          </div>
          <div class="col-md-2">
            <label class="form-label small text-muted">long_window</label>
            <input class="form-control form-control-sm bg-dark text-light border-secondary" name="long_window" type="number" value="20">
          </div>
          <div class="col-12">
            <button type="submit" class="btn btn-primary btn-sm">▶ 백테스트 실행</button>
            <span id="bt-status" class="ms-2 text-muted small"></span>
          </div>
        </form>
      </div>
    </div>
    <div id="bt-result"></div>
    <script>
    document.getElementById('bt-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const params = Object.fromEntries(fd.entries());
      document.getElementById('bt-status').textContent = '실행 중...';
      document.getElementById('bt-result').innerHTML = '';
      try {
        const res = await fetch('/api/backtest/run', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(params)
        });
        const html = await res.text();
        document.getElementById('bt-result').innerHTML = html;
        document.getElementById('bt-status').textContent = '완료';
      } catch(err) {
        document.getElementById('bt-status').textContent = '오류: ' + err;
      }
    });
    </script>"""

    return _render(form_html, "backtest", "/backtest")


@app.post("/api/backtest/run")
async def api_backtest_run(body: dict):
    """백테스트 실행 후 HTML 차트 섹션 반환."""
    import math
    from datetime import timedelta
    from backtest.runner import BacktestRunner
    from backtest.visualization import render_report_html
    from market.snapshot import Candle
    from strategy.impl.ma_crossover import MACrossoverStrategy
    from strategy.impl.rsi_strategy import RsiStrategy
    from strategy.impl.bollinger_strategy import BollingerStrategy
    from strategy.impl.macd_strategy import MacdStrategy

    strategy_name = str(body.get("strategy", "ma_crossover"))
    symbol = str(body.get("symbol", "KRW-BTC"))
    n_candles = int(body.get("n_candles", 120))
    initial_balance = Decimal(str(body.get("initial_balance", "1000000")))
    short_window = int(body.get("short_window", 5))
    long_window = int(body.get("long_window", 20))

    # 사인파 시세 시뮬레이션
    base_time = datetime.now(timezone.utc)
    prices = [
        Decimal(str(round(50000000 + 10000000 * math.sin(2 * math.pi * i / 30), 0)))
        for i in range(n_candles)
    ]
    candles = [
        Candle(
            symbol=symbol, interval="1m",
            open=p, high=p * Decimal("1.003"),
            low=p * Decimal("0.997"), close=p,
            volume=Decimal("1.0"),
            timestamp=base_time + timedelta(minutes=i),
        )
        for i, p in enumerate(prices)
    ]

    # 전략 선택
    strategy_map = {
        "ma_crossover": (MACrossoverStrategy, {"short_window": short_window, "long_window": long_window, "rsi_period": 14}),
        "rsi": (RsiStrategy, {"rsi_period": 14, "oversold_level": 30, "overbought_level": 70}),
        "bollinger": (BollingerStrategy, {"window": long_window, "num_std": 2.0}),
        "macd": (MacdStrategy, {"fast": 12, "slow": 26, "signal": 9}),
    }
    if strategy_name not in strategy_map:
        return HTMLResponse("<p class='text-danger'>지원하지 않는 전략입니다.</p>")

    StrategyClass, params = strategy_map[strategy_name]
    strategy = StrategyClass(name=strategy_name, symbols=[symbol], params=params)

    runner = BacktestRunner(
        strategy=strategy,
        symbol=symbol,
        initial_balance=initial_balance,
    )
    result = runner.run(candles)

    html = render_report_html(result)
    return HTMLResponse(html)


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.dashboard:app", host="0.0.0.0", port=8000, reload=True)
