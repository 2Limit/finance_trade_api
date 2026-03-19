"""
이동평균 지표

sma(prices, window): 단순 이동평균
ema(prices, window): 지수 이동평균
"""
from __future__ import annotations

from decimal import Decimal


def sma(prices: list[Decimal], window: int) -> Decimal | None:
    """Simple Moving Average."""
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / Decimal(window)


def ema(prices: list[Decimal], window: int) -> Decimal | None:
    """Exponential Moving Average."""
    if len(prices) < window:
        return None
    k = Decimal(2) / Decimal(window + 1)
    result = prices[0]
    for price in prices[1:]:
        result = price * k + result * (Decimal(1) - k)
    return result
