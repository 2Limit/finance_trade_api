from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.event import Event, EventBus, EventType
from data.processor.feature_builder import FeatureBuilder
from db.models.signal import SignalModel
from db.session import get_session
from strategy.base import AbstractStrategy, Signal, SignalType

if TYPE_CHECKING:
    from market.snapshot import MarketSnapshot

logger = logging.getLogger(__name__)


class MACrossoverStrategy(AbstractStrategy):
    """
    이동평균 크로스오버 전략.

    매수 조건:
        - 단기 SMA가 장기 SMA를 상향 돌파 (골든크로스)
        - RSI < 70 (과매수 아님)

    매도 조건:
        - 단기 SMA가 장기 SMA를 하향 돌파 (데드크로스)
        - RSI > 30 (과매도 아님)

    params:
        short_window (int): 단기 이동평균 기간 (기본 5)
        long_window  (int): 장기 이동평균 기간 (기본 20)
        rsi_period   (int): RSI 기간 (기본 14)
    """

    def __init__(
        self, name: str, symbols: list[str], params: dict[str, Any]
    ) -> None:
        super().__init__(name, symbols, params)
        self._feature_builder: FeatureBuilder | None = None
        self._prev_cross: dict[str, str] = {}  # symbol → "golden" | "dead" | "none"

    def set_snapshot(self, snapshot: "MarketSnapshot") -> None:
        """TradingEngine이 주입. 직접 생성하지 않음."""
        self._feature_builder = FeatureBuilder(
            snapshot=snapshot,
            short_window=self.params.get("short_window", 5),
            long_window=self.params.get("long_window", 20),
            rsi_period=self.params.get("rsi_period", 14),
        )

    async def on_tick(self, event: Event, bus: EventBus) -> None:
        symbol: str = event.payload["symbol"]
        if symbol not in self.symbols:
            return
        if self._feature_builder is None:
            logger.warning("%s: FeatureBuilder가 주입되지 않았습니다.", self.name)
            return

        features = self._feature_builder.build(symbol)
        if features is None:
            return  # 데이터 부족

        signal = self._evaluate(features)
        if signal is None:
            return

        logger.info(
            "[%s] %s → %s (sma_short=%.2f, sma_long=%.2f, rsi=%.1f)",
            self.name, symbol, signal.signal_type.value,
            float(features.sma_short or 0),
            float(features.sma_long or 0),
            float(features.rsi_14 or 0),
        )

        # DB 저장
        await self._save_signal(signal)

        # EventBus 발행 → OrderManager가 구독
        await bus.publish(
            Event(
                type=EventType.SIGNAL_GENERATED,
                payload={
                    "strategy": self.name,
                    "symbol": symbol,
                    "signal": signal.signal_type.value,
                    "strength": signal.strength,
                    "price": event.payload["price"],
                    "metadata": signal.metadata,
                },
            )
        )

    def on_candle_closed(self, event: Event) -> Signal | None:
        """캔들 확정 시 호출. 현재 구현은 on_tick에서 처리."""
        return None

    def _evaluate(self, features) -> Signal | None:
        symbol = features.symbol
        prev = self._prev_cross.get(symbol, "none")

        if features.is_golden_cross:
            current = "golden"
        elif features.is_dead_cross:
            current = "dead"
        else:
            current = "none"

        self._prev_cross[symbol] = current

        # 크로스 전환 시에만 시그널 발행 (중복 방지)
        if current == "golden" and prev != "golden" and not features.is_overbought:
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                signal_type=SignalType.BUY,
                strength=self._calc_strength(features),
                metadata={
                    "sma_short": float(features.sma_short or 0),
                    "sma_long": float(features.sma_long or 0),
                    "rsi": float(features.rsi_14 or 0),
                },
            )
        if current == "dead" and prev != "dead" and not features.is_oversold:
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                signal_type=SignalType.SELL,
                strength=self._calc_strength(features),
                metadata={
                    "sma_short": float(features.sma_short or 0),
                    "sma_long": float(features.sma_long or 0),
                    "rsi": float(features.rsi_14 or 0),
                },
            )
        return None

    def _calc_strength(self, features) -> float:
        """SMA 이격도 기반 시그널 강도 계산 (0.0~1.0)."""
        if features.sma_short is None or features.sma_long is None:
            return 0.5
        diff = abs(features.sma_short - features.sma_long)
        ratio = float(diff / features.sma_long)
        return min(ratio * 10, 1.0)  # 이격 1% = strength 0.1

    async def _save_signal(self, signal: Signal) -> None:
        try:
            async with get_session() as session:
                session.add(SignalModel(
                    strategy_name=signal.strategy_name,
                    symbol=signal.symbol,
                    signal_type=signal.signal_type.value,
                    strength=signal.strength,
                    metadata_=signal.metadata,
                ))
        except Exception:
            logger.exception("시그널 DB 저장 실패")
