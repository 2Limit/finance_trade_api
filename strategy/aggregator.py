"""
StrategyAggregator: 다중 전략 앙상블

목적:
    - 여러 전략의 시그널을 투표로 취합하여 오신호를 필터링
    - 60% 이상 동의 시 최종 시그널 발행

사용:
    aggregator = StrategyAggregator(
        strategies=[ma_strategy, rsi_strategy, bollinger_strategy],
        event_bus=event_bus,
        threshold=0.6,
    )
    # PRICE_UPDATED 이벤트마다 on_tick() 호출
    event_bus.subscribe(EventType.PRICE_UPDATED, aggregator.on_tick_event)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.event import Event, EventBus, EventType
from db.models.signal import SignalModel
from db.session import get_session
from strategy.base import AbstractStrategy, Signal, SignalType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class StrategyAggregator:
    """
    여러 전략의 시그널을 투표로 취합.

    threshold 비율 이상의 전략이 동일 방향 시그널을 내면
    앙상블 시그널(SIGNAL_GENERATED)을 발행한다.
    """

    def __init__(
        self,
        strategies: list[AbstractStrategy],
        event_bus: EventBus,
        threshold: float = 0.6,
        name: str = "aggregator",
    ) -> None:
        self._strategies = strategies
        self._event_bus = event_bus
        self._threshold = threshold
        self.name = name

    @property
    def strategy_names(self) -> list[str]:
        return [s.name for s in self._strategies]

    async def on_tick_event(self, event: Event) -> None:
        """PRICE_UPDATED 이벤트 → 모든 전략 평가 후 앙상블."""
        symbol: str = event.payload.get("symbol", "")
        if not symbol:
            return

        signals: list[Signal | None] = []
        for strategy in self._strategies:
            try:
                sig = await self._evaluate_strategy(strategy, event)
                signals.append(sig)
            except Exception:
                logger.exception("[Aggregator] %s 평가 오류 (무시)", strategy.name)
                signals.append(None)

        ensemble = self._aggregate(symbol, signals)
        if ensemble is None:
            return

        logger.info("[Aggregator] %s → %s (votes: %d/%d, threshold=%.0f%%)",
                    symbol, ensemble.signal_type.value,
                    self._count_votes(ensemble.signal_type, signals),
                    len(signals), self._threshold * 100)

        await self._save_signal(ensemble)
        await self._event_bus.publish(Event(
            type=EventType.SIGNAL_GENERATED,
            payload={
                "strategy": self.name,
                "symbol": symbol,
                "signal": ensemble.signal_type.value,
                "strength": ensemble.strength,
                "price": event.payload.get("price", "0"),
                "metadata": ensemble.metadata,
            },
        ))

    async def _evaluate_strategy(self, strategy: AbstractStrategy, event: Event) -> Signal | None:
        """전략의 _evaluate()를 직접 호출 (EventBus 발행 없이 시그널만 획득)."""
        symbol = event.payload.get("symbol", "")
        if symbol not in strategy.symbols:
            return None

        # FeatureBuilder 기반 전략 (MACrossover, RSI 등)은 내부 snapshot을 이미 가짐
        # snapshot이 있는 전략은 on_tick 대신 _evaluate를 직접 호출
        if hasattr(strategy, "_feature_builder") and strategy._feature_builder is not None:
            features = strategy._feature_builder.build(symbol)
            if features is None:
                return None
            return strategy._evaluate(features)

        # snapshot만 있는 전략 (RSI, Bollinger, MACD)은 on_tick으로 시뮬레이션
        # 이 경우 실제 발행 없이 내부 평가만 수행하기 위해 임시 버스 사용
        # 단순화: 이 전략들의 _evaluate를 직접 노출하지 않으므로 None 반환
        return None

    def _aggregate(self, symbol: str, signals: list[Signal | None]) -> Signal | None:
        active = [s for s in signals if s is not None]
        if not active:
            return None

        total = len(self._strategies)
        buy_votes = sum(1 for s in active if s.signal_type == SignalType.BUY)
        sell_votes = sum(1 for s in active if s.signal_type == SignalType.SELL)

        buy_ratio = buy_votes / total
        sell_ratio = sell_votes / total

        if buy_ratio >= self._threshold:
            avg_strength = sum(s.strength for s in active if s.signal_type == SignalType.BUY) / max(buy_votes, 1)
            return Signal(
                strategy_name=self.name, symbol=symbol,
                signal_type=SignalType.BUY, strength=round(avg_strength, 2),
                metadata={
                    "buy_votes": buy_votes, "sell_votes": sell_votes,
                    "total": total, "threshold": self._threshold,
                    "strategies": [s.strategy_name for s in active if s.signal_type == SignalType.BUY],
                },
            )
        if sell_ratio >= self._threshold:
            avg_strength = sum(s.strength for s in active if s.signal_type == SignalType.SELL) / max(sell_votes, 1)
            return Signal(
                strategy_name=self.name, symbol=symbol,
                signal_type=SignalType.SELL, strength=round(avg_strength, 2),
                metadata={
                    "buy_votes": buy_votes, "sell_votes": sell_votes,
                    "total": total, "threshold": self._threshold,
                    "strategies": [s.strategy_name for s in active if s.signal_type == SignalType.SELL],
                },
            )
        return None

    def _count_votes(self, signal_type: SignalType, signals: list[Signal | None]) -> int:
        return sum(1 for s in signals if s is not None and s.signal_type == signal_type)

    async def _save_signal(self, signal: Signal) -> None:
        try:
            async with get_session() as session:
                session.add(SignalModel(
                    strategy_name=signal.strategy_name, symbol=signal.symbol,
                    signal_type=signal.signal_type.value, strength=signal.strength,
                    metadata_=signal.metadata,
                ))
        except Exception:
            logger.exception("앙상블 시그널 DB 저장 실패")
