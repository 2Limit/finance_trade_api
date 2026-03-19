from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from data.processor.indicators import ema, rsi, sma

if TYPE_CHECKING:
    from market.snapshot import Candle, MarketSnapshot


@dataclass
class Features:
    """전략이 소비하는 피처 집합."""

    symbol: str
    close_prices: list[Decimal]
    current_price: Decimal

    sma_short: Decimal | None  # 단기 SMA
    sma_long: Decimal | None   # 장기 SMA
    ema_short: Decimal | None  # 단기 EMA
    ema_long: Decimal | None   # 장기 EMA
    rsi_14: Decimal | None     # RSI(14)

    @property
    def is_golden_cross(self) -> bool:
        """단기 SMA > 장기 SMA (골든크로스)."""
        if self.sma_short is None or self.sma_long is None:
            return False
        return self.sma_short > self.sma_long

    @property
    def is_dead_cross(self) -> bool:
        """단기 SMA < 장기 SMA (데드크로스)."""
        if self.sma_short is None or self.sma_long is None:
            return False
        return self.sma_short < self.sma_long

    @property
    def is_overbought(self) -> bool:
        return self.rsi_14 is not None and self.rsi_14 > Decimal("70")

    @property
    def is_oversold(self) -> bool:
        return self.rsi_14 is not None and self.rsi_14 < Decimal("30")


class FeatureBuilder:
    """
    MarketSnapshot → Features 변환.

    전략은 raw 캔들 데이터에 직접 접근하지 않고
    FeatureBuilder가 계산한 Features를 사용한다.
    """

    def __init__(
        self,
        snapshot: "MarketSnapshot",
        short_window: int = 5,
        long_window: int = 20,
        rsi_period: int = 14,
    ) -> None:
        self._snapshot = snapshot
        self._short_window = short_window
        self._long_window = long_window
        self._rsi_period = rsi_period

    def build(self, symbol: str) -> Features | None:
        """심볼의 최신 Features를 계산. 데이터 부족 시 None 반환."""
        required = max(self._long_window, self._rsi_period + 1)
        candles = self._snapshot.get_candles(symbol, limit=required + 10)
        if len(candles) < required:
            return None

        closes = [c.close for c in candles]
        current = closes[-1]

        return Features(
            symbol=symbol,
            close_prices=closes,
            current_price=current,
            sma_short=sma(closes, self._short_window),
            sma_long=sma(closes, self._long_window),
            ema_short=ema(closes, self._short_window),
            ema_long=ema(closes, self._long_window),
            rsi_14=rsi(closes, self._rsi_period),
        )
