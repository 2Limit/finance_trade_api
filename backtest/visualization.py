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
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backtest.runner import BacktestResult


def _to_b64(fig) -> str:
    """matplotlib Figure → base64 PNG 문자열."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _dark_style(fig, ax) -> None:
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#161b22")
    ax.tick_params(colors="#8b949e")
    ax.xaxis.label.set_color("#8b949e")
    ax.yaxis.label.set_color("#8b949e")
    ax.title.set_color("#c9d1d9")
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")
    ax.grid(color="#21262d", linestyle="--", linewidth=0.5)


def _auto_xaxis(ax, timestamps: list) -> str:
    """
    타임스탬프 목록의 전체 범위를 보고 X축 포맷/로케이터를 자동 설정.

    반환값: 사람이 읽기 좋은 단위 문자열 (축 레이블 용도)
    """
    import matplotlib.dates as mdates

    if len(timestamps) < 2:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        return "Time"

    span: timedelta = timestamps[-1] - timestamps[0]
    total_seconds = span.total_seconds()

    if total_seconds < 3600 * 2:           # 2시간 미만 → 분 단위
        fmt = "%H:%M"
        locator = mdates.MinuteLocator(byminute=range(0, 60, max(1, int(total_seconds / 60 / 6))))
        xlabel = "Time (HH:MM)"

    elif total_seconds < 3600 * 24:        # 24시간 미만 → 시 단위
        fmt = "%H:%M"
        locator = mdates.HourLocator(interval=max(1, int(total_seconds / 3600 / 6)))
        xlabel = "Time (HH:MM)"

    elif total_seconds < 3600 * 24 * 3:   # 3일 미만 → 날짜 + 시간
        fmt = "%m/%d %H:%M"
        locator = mdates.HourLocator(interval=max(1, int(total_seconds / 3600 / 8)))
        xlabel = "Date / Time"

    elif total_seconds < 3600 * 24 * 30:  # 30일 미만 → 날짜
        fmt = "%m/%d"
        locator = mdates.DayLocator(interval=max(1, int(span.days / 6)))
        xlabel = "Date"

    elif total_seconds < 3600 * 24 * 365: # 1년 미만 → 월-일
        fmt = "%Y/%m/%d"
        locator = mdates.WeekdayLocator(interval=max(1, int(span.days / 30)))
        xlabel = "Date"

    else:                                  # 1년 이상 → 연-월
        fmt = "%Y/%m"
        locator = mdates.MonthLocator(interval=max(1, int(span.days / 365 * 2)))
        xlabel = "Month"

    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))

    # 레이블 겹침 방지: 문자열이 길면 45° 회전
    rotation = 30 if len(fmt) > 5 else 0
    for label in ax.get_xticklabels():
        label.set_rotation(rotation)
        label.set_ha("right" if rotation else "center")

    return xlabel


def plot_equity_curve(result: "BacktestResult") -> str:
    """자산 곡선 차트 → base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

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
    ax.axhline(equities[0], color="#8b949e", linestyle="--", linewidth=0.8, label="Initial Capital")
    ax.set_title(f"Equity Curve — {result.strategy_name} / {result.symbol}")
    ax.set_ylabel("Balance (KRW)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend(facecolor="#21262d", labelcolor="#c9d1d9", edgecolor="#30363d")

    xlabel = _auto_xaxis(ax, timestamps)
    ax.set_xlabel(xlabel)

    plt.tight_layout()
    b64 = _to_b64(fig)
    plt.close(fig)
    return b64


def plot_drawdown(result: "BacktestResult") -> str:
    """드로다운 차트 → base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

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
    ax.set_title("Drawdown (%)")
    ax.set_ylabel("Drawdown (%)")

    xlabel = _auto_xaxis(ax, timestamps)
    ax.set_xlabel(xlabel)

    plt.tight_layout()
    b64 = _to_b64(fig)
    plt.close(fig)
    return b64


def plot_trade_markers(result: "BacktestResult") -> str:
    """전체 가격선 + 매수/매도 마커 차트 → base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    trades = result.trades
    if not trades:
        return ""

    # 캔들 전체 가격선: period_start ~ period_end 사이를 선형 보간
    # (실제 체결 포인트 외 가격선은 trade timestamps 기준으로만 그림)
    all_times  = [t.timestamp for t in trades]
    all_prices = [float(t.price) for t in trades]

    buy_times   = [t.timestamp for t in trades if t.side == "buy"]
    buy_prices  = [float(t.price) for t in trades if t.side == "buy"]
    sell_times  = [t.timestamp for t in trades if t.side == "sell"]
    sell_prices = [float(t.price) for t in trades if t.side == "sell"]

    fig, ax = plt.subplots(figsize=(10, 4))
    _dark_style(fig, ax)

    ax.plot(all_times, all_prices, color="#58a6ff", linewidth=1.0, alpha=0.7, label="Fill Price")
    ax.scatter(buy_times,  buy_prices,  color="#3fb950", marker="^", s=80, zorder=5, label="BUY")
    ax.scatter(sell_times, sell_prices, color="#f85149", marker="v", s=80, zorder=5, label="SELL")
    ax.set_title(f"Trade Markers — {result.symbol}")
    ax.set_ylabel("Price (KRW)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend(facecolor="#21262d", labelcolor="#c9d1d9", edgecolor="#30363d")

    xlabel = _auto_xaxis(ax, all_times)
    ax.set_xlabel(xlabel)

    plt.tight_layout()
    b64 = _to_b64(fig)
    plt.close(fig)
    return b64


def render_report_html(result: "BacktestResult") -> str:
    """BacktestResult를 완전한 HTML 섹션으로 렌더링."""
    equity_b64   = plot_equity_curve(result)
    drawdown_b64 = plot_drawdown(result)
    trade_b64    = plot_trade_markers(result)

    def _img(b64: str) -> str:
        if not b64:
            return '<p class="text-muted text-center py-3">거래 없음 — 시그널이 발생하지 않았습니다</p>'
        return f'<img src="data:image/png;base64,{b64}" class="img-fluid rounded" alt="chart">'

    ret_color = "pnl-pos" if result.total_return >= 0 else "pnl-neg"
    sign = "+" if result.total_return >= 0 else ""

    # 기간 표시: span에 따라 단위 선택
    span = result.period_end - result.period_start
    if span.total_seconds() < 3600 * 2:
        period_str = f"{int(span.total_seconds() / 60)}분"
    elif span.total_seconds() < 3600 * 24:
        period_str = f"{span.total_seconds() / 3600:.1f}시간"
    elif span.days < 30:
        period_str = f"{span.days}일"
    else:
        period_str = f"{span.days // 30}개월 {span.days % 30}일"

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
        <div class="text-muted small">백테스트 기간</div>
        <div class="stat-value text-secondary" style="font-size:1.1rem">{period_str}</div>
      </div></div>
    </div>
    <div class="row g-2">
      <div class="col-12">{_img(equity_b64)}</div>
      <div class="col-12">{_img(drawdown_b64)}</div>
      <div class="col-12">{_img(trade_b64)}</div>
    </div>"""
    return stats
