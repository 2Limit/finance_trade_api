"""
MACD 전략 (Moving Average Convergence Divergence)

매수 조건:
    - MACD 라인이 시그널 라인을 상향 돌파 (골든크로스)

매도 조건:
    - MACD 라인이 시그널 라인을 하향 이탈 (데드크로스)

params:
    fast   (int): 단기 EMA 기간 (기본 12)
    slow   (int): 장기 EMA 기간 (기본 26)
    signal (int): 시그널 EMA 기간 (기본 9)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.event import Event, EventBus, EventType
from data.processor.indicators import macd
from db.models.signal import SignalModel
from db.session import get_session
from strategy.base import AbstractStrategy, Signal, SignalType

if TYPE_CHECKING:
    from market.snapshot import MarketSnapshot

logger = logging.getLogger(__name__)

_PARAM_SCHEMA = {
    "fast":   {"type": "int", "default": 12, "description": "MACD 단기 EMA 기간"},
    "slow":   {"type": "int", "default": 26, "description": "MACD 장기 EMA 기간"},
    "signal": {"type": "int", "default": 9,  "description": "시그널 라인 EMA 기간"},
}


class MacdStrategy(AbstractStrategy):
    """MACD 크로스오버 전략."""

    def __init__(self, name: str, symbols: list[str], params: dict[str, Any]) -> None:
        super().__init__(name, symbols, params)
        self._snapshot: "MarketSnapshot | None" = None
        # symbol → "above" | "below"  (macd > signal 이면 above)
        self._prev_position: dict[str, str] = {}

    def set_snapshot(self, snapshot: "MarketSnapshot") -> None:
        self._snapshot = snapshot

    def required_candles(self) -> int:
        # MACD는 slow + signal 개 이상의 데이터 필요
        slow = self.params.get("slow", 26)
        signal = self.params.get("signal", 9)
        return slow + signal + 15

    def update_params(self, new_params: dict) -> None:
        super().update_params(new_params)
        self._prev_position.clear()

    def param_schema(self) -> dict[str, dict]:
        return _PARAM_SCHEMA

    async def on_tick(self, event: Event, bus: EventBus) -> None:
        symbol: str = event.payload["symbol"]
        if symbol not in self.symbols or self._snapshot is None:
            return

        fast = self.params.get("fast", 12)
        slow = self.params.get("slow", 26)
        sig_period = self.params.get("signal", 9)

        candles = self._snapshot.get_candles(symbol, limit=slow + sig_period + 20)
        if len(candles) < slow + sig_period:
            return

        closes = [c.close for c in candles]
        result = macd(closes, fast, slow, sig_period)
        if result is None:
            return

        macd_line, signal_line, histogram = result
        signal = self._evaluate_macd(symbol, macd_line, signal_line, histogram)
        if signal is None:
            return

        logger.info("[%s] %s → %s (MACD=%.4f, Signal=%.4f, Hist=%.4f)",
                    self.name, symbol, signal.signal_type.value,
                    float(macd_line), float(signal_line), float(histogram))
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
        fast = self.params.get("fast", 12)
        slow = self.params.get("slow", 26)
        sig_period = self.params.get("signal", 9)
        result = macd(features.close_prices, fast, slow, sig_period)
        if result is None:
            return None
        macd_line, signal_line, histogram = result
        return self._evaluate_macd(features.symbol, macd_line, signal_line, histogram)

    def _evaluate_macd(
        self, symbol: str, macd_line: Decimal, signal_line: Decimal, histogram: Decimal
    ) -> Signal | None:
        prev = self._prev_position.get(symbol)
        current = "above" if macd_line > signal_line else "below"
        self._prev_position[symbol] = current

        if prev is None:
            return None

        # 하향 → 상향 돌파 (골든크로스) → BUY
        if prev == "below" and current == "above":
            strength = min(float(abs(histogram)) / 100, 1.0)
            return Signal(
                strategy_name=self.name, symbol=symbol,
                signal_type=SignalType.BUY, strength=round(strength, 2),
                metadata={"macd": float(macd_line), "signal": float(signal_line), "histogram": float(histogram)},
            )
        # 상향 → 하향 이탈 (데드크로스) → SELL
        if prev == "above" and current == "below":
            strength = min(float(abs(histogram)) / 100, 1.0)
            return Signal(
                strategy_name=self.name, symbol=symbol,
                signal_type=SignalType.SELL, strength=round(strength, 2),
                metadata={"macd": float(macd_line), "signal": float(signal_line), "histogram": float(histogram)},
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
