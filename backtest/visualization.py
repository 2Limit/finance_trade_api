"""
백테스트 시각화 (matplotlib → base64 PNG)

HTML 대시보드에 임베드 가능한 차트를 생성한다.

제공 함수:
    plot_equity_curve(result) → base64 str
    plot_drawdown(result)     → base64 str
    plot_trade_markers(result, prices) → base64 str
    render_report_html(result) → str (완전한 HTML 섹션)
"""
from __future__ import annotations

import base64
import io
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backtest.runner import BacktestResult


def _to_b64(fig) -> str:
    """matplotlib Figure → base64 PNG 문자열."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _dark_style(fig, ax):
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#161b22")
    ax.tick_params(colors="#8b949e")
    ax.xaxis.label.set_color("#8b949e")
    ax.yaxis.label.set_color("#8b949e")
    ax.title.set_color("#c9d1d9")
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")
    ax.grid(color="#21262d", linestyle="--", linewidth=0.5)


def plot_equity_curve(result: "BacktestResult") -> str:
    """자산 곡선 차트 → base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    trades = result.trades
    if not trades:
        return ""

    timestamps = [result.period_start] + [t.timestamp for t in trades]
    equities: list[float] = [float(result.initial_balance)]

    running = float(result.initial_balance)
    for t in trades:
        if t.side == "sell":
            running += float(t.pnl)
        equities.append(running)

    fig, ax = plt.subplots(figsize=(10, 4))
    _dark_style(fig, ax)

    color = "#3fb950" if equities[-1] >= equities[0] else "#f85149"
    ax.plot(timestamps, equities, color=color, linewidth=1.5)
    ax.fill_between(timestamps, equities[0], equities, alpha=0.15, color=color)
    ax.axhline(equities[0], color="#8b949e", linestyle="--", linewidth=0.8, label="초기 자본")
    ax.set_title(f"자산 곡선 — {result.strategy_name} / {result.symbol}")
    ax.set_xlabel("날짜")
    ax.set_ylabel("자산 (KRW)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend(facecolor="#21262d", labelcolor="#c9d1d9", edgecolor="#30363d")
    plt.tight_layout()

    b64 = _to_b64(fig)
    plt.close(fig)
    return b64


def plot_drawdown(result: "BacktestResult") -> str:
    """드로다운 차트 → base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    trades = result.trades
    if not trades:
        return ""

    timestamps = [result.period_start] + [t.timestamp for t in trades]
    equities: list[float] = [float(result.initial_balance)]
    running = float(result.initial_balance)
    for t in trades:
        if t.side == "sell":
            running += float(t.pnl)
        equities.append(running)

    peak = equities[0]
    drawdowns = []
    for e in equities:
        if e > peak:
            peak = e
        dd = (e - peak) / peak * 100 if peak > 0 else 0.0
        drawdowns.append(dd)

    fig, ax = plt.subplots(figsize=(10, 3))
    _dark_style(fig, ax)

    ax.fill_between(timestamps, 0, drawdowns, color="#f85149", alpha=0.6)
    ax.plot(timestamps, drawdowns, color="#f85149", linewidth=0.8)
    ax.set_title("드로다운 (%)")
    ax.set_xlabel("날짜")
    ax.set_ylabel("드로다운 (%)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    plt.tight_layout()

    b64 = _to_b64(fig)
    plt.close(fig)
    return b64


def plot_trade_markers(result: "BacktestResult") -> str:
    """가격 + 매수/매도 마커 차트 → base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    trades = result.trades
    if not trades:
        return ""

    all_times = [t.timestamp for t in trades]
    all_prices = [float(t.price) for t in trades]

    buy_times  = [t.timestamp for t in trades if t.side == "buy"]
    buy_prices = [float(t.price) for t in trades if t.side == "buy"]
    sell_times  = [t.timestamp for t in trades if t.side == "sell"]
    sell_prices = [float(t.price) for t in trades if t.side == "sell"]

    fig, ax = plt.subplots(figsize=(10, 4))
    _dark_style(fig, ax)

    ax.plot(all_times, all_prices, color="#58a6ff", linewidth=1.0, alpha=0.7, label="체결가")
    ax.scatter(buy_times, buy_prices, color="#3fb950", marker="^", s=80, zorder=5, label="BUY")
    ax.scatter(sell_times, sell_prices, color="#f85149", marker="v", s=80, zorder=5, label="SELL")
    ax.set_title(f"거래 마커 — {result.symbol}")
    ax.set_xlabel("날짜")
    ax.set_ylabel("가격 (KRW)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend(facecolor="#21262d", labelcolor="#c9d1d9", edgecolor="#30363d")
    plt.tight_layout()

    b64 = _to_b64(fig)
    plt.close(fig)
    return b64


def render_report_html(result: "BacktestResult") -> str:
    """BacktestResult를 완전한 HTML 섹션으로 렌더링."""
    equity_b64  = plot_equity_curve(result)
    drawdown_b64 = plot_drawdown(result)
    trade_b64   = plot_trade_markers(result)

    def _img(b64: str) -> str:
        if not b64:
            return '<p class="text-muted text-center">데이터 없음</p>'
        return f'<img src="data:image/png;base64,{b64}" class="img-fluid rounded" alt="chart">'

    ret_color = "pnl-pos" if result.total_return >= 0 else "pnl-neg"
    sign = "+" if result.total_return >= 0 else ""

    stats = f"""
    <div class="row g-2 mb-3">
      <div class="col-6 col-md-2"><div class="stat-card">
        <div class="text-muted small">수익률</div>
        <div class="stat-value {ret_color}">{sign}{result.total_return_pct:.2f}%</div>
      </div></div>
      <div class="col-6 col-md-2"><div class="stat-card">
        <div class="text-muted small">최종 자산</div>
        <div class="stat-value text-light">{float(result.final_balance):,.0f}</div>
      </div></div>
      <div class="col-6 col-md-2"><div class="stat-card">
        <div class="text-muted small">총 거래</div>
        <div class="stat-value text-info">{len(result.trades)}</div>
      </div></div>
      <div class="col-6 col-md-2"><div class="stat-card">
        <div class="text-muted small">승률</div>
        <div class="stat-value text-warning">{result.win_rate:.1%}</div>
      </div></div>
      <div class="col-6 col-md-2"><div class="stat-card">
        <div class="text-muted small">손익비</div>
        <div class="stat-value text-primary">{result.profit_factor:.2f}</div>
      </div></div>
      <div class="col-6 col-md-2"><div class="stat-card">
        <div class="text-muted small">총 수수료</div>
        <div class="stat-value text-secondary">{float(result.total_fee):,.0f}</div>
      </div></div>
    </div>
    <div class="row g-2">
      <div class="col-12">{_img(equity_b64)}</div>
      <div class="col-12">{_img(drawdown_b64)}</div>
      <div class="col-12">{_img(trade_b64)}</div>
    </div>"""
    return stats
