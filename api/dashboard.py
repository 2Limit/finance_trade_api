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
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db.models  # noqa: F401  — 모든 모델 등록
from config import get_settings
from db.models.balance import BalanceHistoryModel
from db.models.order import OrderModel
from db.models.position import PositionModel
from db.models.signal import SignalModel

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

_HTML_BASE = """<!DOCTYPE html>
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
    nav = {f"nav_{k}": "" for k in ["overview", "positions", "orders", "signals", "balances"]}
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


# ── JSON API ─────────────────────────────────────────────────────────────────

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


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.dashboard:app", host="0.0.0.0", port=8000, reload=True)
