"""
RSI (Relative Strength Index) 지표

rsi(prices, period=14): RSI 값 반환 (0~100)
"""
from __future__ import annotations

from decimal import Decimal


def rsi(prices: list[Decimal], period: int = 14) -> Decimal | None:
    """RSI 계산. prices는 종가 리스트."""
    if len(prices) < period + 1:
        return None

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else Decimal("0") for d in deltas]
    losses = [abs(d) if d < 0 else Decimal("0") for d in deltas]

    avg_gain = sum(gains[-period:]) / Decimal(period)
    avg_loss = sum(losses[-period:]) / Decimal(period)

    if avg_loss == Decimal("0"):
        return Decimal("100")

    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
