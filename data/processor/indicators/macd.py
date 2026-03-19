"""MACD (Moving Average Convergence Divergence) 지표."""
from __future__ import annotations

from decimal import Decimal
from .moving_average import ema


def macd(
    prices: list[Decimal],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[Decimal, Decimal, Decimal] | None:
    """
    MACD 계산.

    Returns:
        (macd_line, signal_line, histogram) 또는 데이터 부족 시 None
    """
    if len(prices) < slow + signal:
        return None

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    if ema_fast is None or ema_slow is None:
        return None

    macd_line = ema_fast - ema_slow

    # signal line: MACD 히스토리가 필요하지만 단순 근사로 EMA 적용
    # 실용적 근사: 마지막 N 봉 MACD를 재계산하여 signal EMA 산출
    macd_history: list[Decimal] = []
    for i in range(signal + slow, len(prices) + 1):
        sub = prices[:i]
        ef = ema(sub, fast)
        es = ema(sub, slow)
        if ef is not None and es is not None:
            macd_history.append(ef - es)

    if len(macd_history) < signal:
        return None

    signal_line = ema(macd_history, signal)
    if signal_line is None:
        return None

    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram
