"""
RSI 전략 (Relative Strength Index)

매수 조건:
    - RSI가 oversold_level 미만에서 → oversold_level 이상 회복 시 BUY

매도 조건:
    - RSI가 overbought_level 초과에서 → overbought_level 이하 이탈 시 SELL

params:
    rsi_period      (int):   RSI 계산 기간 (기본 14)
    oversold_level  (float): 과매도 기준 (기본 30)
    overbought_level(float): 과매수 기준 (기본 70)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.event import Event, EventBus, EventType
from data.processor.indicators import rsi, sma
from db.models.signal import SignalModel
from db.session import get_session
from strategy.base import AbstractStrategy, Signal, SignalType

if TYPE_CHECKING:
    from market.snapshot import MarketSnapshot

logger = logging.getLogger(__name__)

_PARAM_SCHEMA = {
    "rsi_period":       {"type": "int",   "default": 14,  "description": "RSI 계산 기간"},
    "oversold_level":   {"type": "float", "default": 30.0, "description": "과매도 기준 (이 미만 진입 후 회복 시 BUY)"},
    "overbought_level": {"type": "float", "default": 70.0, "description": "과매수 기준 (이 초과 진입 후 이탈 시 SELL)"},
}


class RsiStrategy(AbstractStrategy):
    """RSI 과매도/과매수 반전 전략."""

    def __init__(self, name: str, symbols: list[str], params: dict[str, Any]) -> None:
        super().__init__(name, symbols, params)
        self._snapshot: "MarketSnapshot | None" = None
        # symbol → "oversold" | "overbought" | "neutral"
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

        period = self.params.get("rsi_period", 14)
        oversold = float(self.params.get("oversold_level", 30))
        overbought = float(self.params.get("overbought_level", 70))

        candles = self._snapshot.get_candles(symbol, limit=period + 10)
        if len(candles) < period + 1:
            return

        closes = [c.close for c in candles]
        rsi_val = rsi(closes, period)
        if rsi_val is None:
            return

        signal = self._evaluate_rsi(symbol, float(rsi_val), oversold, overbought)
        if signal is None:
            return

        logger.info("[%s] %s → %s (RSI=%.1f)", self.name, symbol, signal.signal_type.value, float(rsi_val))
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
        if features.rsi_14 is None:
            return None
        oversold = float(self.params.get("oversold_level", 30))
        overbought = float(self.params.get("overbought_level", 70))
        return self._evaluate_rsi(features.symbol, float(features.rsi_14), oversold, overbought)

    def _evaluate_rsi(self, symbol: str, rsi_val: float, oversold: float, overbought: float) -> Signal | None:
        prev = self._prev_zone.get(symbol, "neutral")

            if rsi_val < oversold:
            zone = "oversold"
        elif rsi_val > overbought:
            zone = "overbought"
        else:
            zone = "neutral"

        self._prev_zone[symbol] = zone

        # 과매도 → 중립 회복 시 BUY
        if prev == "oversold" and zone == "neutral":
            strength = min((rsi_val - oversold) / max(50 - oversold, 1), 1.0)
            return Signal(
                strategy_name=self.name, symbol=symbol,
                signal_type=SignalType.BUY, strength=round(strength, 2),
                metadata={"rsi": rsi_val, "zone_change": f"{prev}→{zone}"},
            )
        # 과매수 → 중립 이탈 시 SELL
        if prev == "overbought" and zone == "neutral":
            strength = min((overbought - rsi_val) / max(overbought - 50, 1), 1.0)
            return Signal(
                strategy_name=self.name, symbol=symbol,
                signal_type=SignalType.SELL, strength=round(strength, 2),
                metadata={"rsi": rsi_val, "zone_change": f"{prev}→{zone}"},
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
