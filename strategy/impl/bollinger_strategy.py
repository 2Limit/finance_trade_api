"""
볼린저 밴드 전략 (Bollinger Band)

매수 조건:
    - 전 봉이 하단 밴드 이하 터치 후 현재 봉 하단 밴드 위로 회복 → BUY

매도 조건:
    - 전 봉이 상단 밴드 이상 터치 후 현재 봉 상단 밴드 아래로 하락 → SELL

params:
    window   (int):   이동평균 기간 (기본 20)
    num_std  (float): 표준편차 배수 (기본 2.0)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.event import Event, EventBus, EventType
from data.processor.indicators import bollinger_bands
from db.models.signal import SignalModel
from db.session import get_session
from strategy.base import AbstractStrategy, Signal, SignalType

if TYPE_CHECKING:
    from market.snapshot import MarketSnapshot

logger = logging.getLogger(__name__)

_PARAM_SCHEMA = {
    "window":  {"type": "int",   "default": 20,  "description": "볼린저 밴드 이동평균 기간"},
    "num_std": {"type": "float", "default": 2.0, "description": "표준편차 배수 (밴드 폭)"},
}


class BollingerStrategy(AbstractStrategy):
    """볼린저 밴드 반전 전략."""

    def __init__(self, name: str, symbols: list[str], params: dict[str, Any]) -> None:
        super().__init__(name, symbols, params)
        self._snapshot: "MarketSnapshot | None" = None
        # symbol → "below_lower" | "above_upper" | "neutral"
        self._prev_zone: dict[str, str] = {}

    def set_snapshot(self, snapshot: "MarketSnapshot") -> None:
        self._snapshot = snapshot

    def update_params(self, new_params: dict) -> None:
        super().update_params(new_params)
        self._prev_zone.clear()

    def param_schema(self) -> dict[str, dict]:
        return _PARAM_SCHEMA

    async def on_tick(self, event: Event, bus: EventBus) -> None:
        symbol: str = event.payload["symbol"]
        if symbol not in self.symbols or self._snapshot is None:
            return

        window = self.params.get("window", 20)
        num_std = float(self.params.get("num_std", 2.0))

        candles = self._snapshot.get_candles(symbol, limit=window + 10)
        if len(candles) < window:
            return

        closes = [c.close for c in candles]
        bands = bollinger_bands(closes, window, num_std)
        if bands is None:
            return

        upper, middle, lower = bands
        current = closes[-1]

        signal = self._evaluate_bands(symbol, current, upper, lower)
        if signal is None:
            return

        bw = float((upper - lower) / middle * 100)
        logger.info("[%s] %s → %s (price=%.0f, upper=%.0f, lower=%.0f, BW=%.2f%%)",
                    self.name, symbol, signal.signal_type.value,
                    float(current), float(upper), float(lower), bw)
        await self._save_signal(signal)
        await bus.publish(Event(
            type=EventType.SIGNAL_GENERATED,
            payload={
                "strategy": self.name,
                "symbol": symbol,
                "signal": signal.signal_type.value,
                "strength": signal.strength,
                "price": event.payload["price"],
                "metadata": signal.metadata,
            },
        ))

    def on_candle_closed(self, event: Event) -> Signal | None:
        return None

    def _evaluate(self, features) -> Signal | None:
        """BacktestRunner 호환용 — Features 객체로 평가."""
        window = self.params.get("window", 20)
        num_std = float(self.params.get("num_std", 2.0))
        bands = bollinger_bands(features.close_prices, window, num_std)
        if bands is None:
            return None
        upper, _, lower = bands
        return self._evaluate_bands(features.symbol, features.current_price, upper, lower)

    def _evaluate_bands(self, symbol: str, price: Decimal, upper: Decimal, lower: Decimal) -> Signal | None:
        prev = self._prev_zone.get(symbol, "neutral")

        if price <= lower:
            zone = "below_lower"
        elif price >= upper:
            zone = "above_upper"
        else:
            zone = "neutral"

        self._prev_zone[symbol] = zone

        band_width = upper - lower
        if band_width == 0:
            return None

        # 하단 밴드 터치 후 반등 → BUY
        if prev == "below_lower" and zone == "neutral":
            strength = min(float((price - lower) / band_width), 1.0)
            return Signal(
                strategy_name=self.name, symbol=symbol,
                signal_type=SignalType.BUY, strength=round(strength, 2),
                metadata={"price": float(price), "upper": float(upper), "lower": float(lower)},
            )
        # 상단 밴드 터치 후 하락 → SELL
        if prev == "above_upper" and zone == "neutral":
            strength = min(float((upper - price) / band_width), 1.0)
            return Signal(
                strategy_name=self.name, symbol=symbol,
                signal_type=SignalType.SELL, strength=round(strength, 2),
                metadata={"price": float(price), "upper": float(upper), "lower": float(lower)},
            )
        return None

    async def _save_signal(self, signal: Signal) -> None:
        try:
            async with get_session() as session:
                session.add(SignalModel(
                    strategy_name=signal.strategy_name, symbol=signal.symbol,
                    signal_type=signal.signal_type.value, strength=signal.strength,
                    metadata_=signal.metadata,
                ))
        except Exception:
            logger.exception("시그널 DB 저장 실패")
