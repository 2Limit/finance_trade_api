"""볼린저 밴드 지표."""
from __future__ import annotations

import math
from decimal import Decimal


def bollinger_bands(
    prices: list[Decimal], window: int = 20, num_std: float = 2.0
) -> tuple[Decimal, Decimal, Decimal] | None:
    """
    볼린저 밴드 계산.

    Returns:
        (upper, middle, lower) 또는 데이터 부족 시 None
    """
    if len(prices) < window:
        return None

    window_prices = prices[-window:]
    middle = sum(window_prices) / Decimal(window)

    variance = sum((p - middle) ** 2 for p in window_prices) / Decimal(window)
    std = Decimal(str(math.sqrt(float(variance))))
    band = std * Decimal(str(num_std))

    return middle + band, middle, middle - band
