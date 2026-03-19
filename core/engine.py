"""
TradingEngine: 트레이딩 루프 오케스트레이터

책임:
    - 컴포넌트 초기화 및 의존성 주입
    - 실시간 루프 시작/종료
    - 이벤트 라우팅 (EventBus 기반)

흐름:
    start() → MarketFeed.connect() → 전략 등록 → 루프 실행
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from core.event import EventBus, EventType, Event

if TYPE_CHECKING:
    from broker.base import AbstractBroker
    from market.feed import AbstractMarketFeed
    from strategy.base import AbstractStrategy
    from execution.order_manager import OrderManager
    from portfolio.position import PositionManager
    from alert.base import AbstractAlert

logger = logging.getLogger(__name__)


class TradingEngine:
    """실시간 트레이딩 엔진."""

    def __init__(
        self,
        broker: "AbstractBroker",
        feed: "AbstractMarketFeed",
        order_manager: "OrderManager",
        position_manager: "PositionManager",
        event_bus: EventBus,
    ) -> None:
        self.broker = broker
        self.feed = feed
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.event_bus = event_bus

        self._strategies: list["AbstractStrategy"] = []
        self._alerts: list["AbstractAlert"] = []
        self._running = False

    def register_strategy(self, strategy: "AbstractStrategy") -> None:
        self._strategies.append(strategy)
        logger.info("Strategy registered: %s", strategy.name)

    def register_alert(self, alert: "AbstractAlert") -> None:
        self._alerts.append(alert)

    async def start(self) -> None:
        logger.info("TradingEngine starting...")
        self._running = True
        self._register_event_handlers()
        await asyncio.gather(
            self.feed.connect(),
            self._heartbeat(),
        )

    async def stop(self) -> None:
        logger.info("TradingEngine stopping...")
        self._running = False
        await self.feed.disconnect()

    def _register_event_handlers(self) -> None:
        # 가격 이벤트 → 전략으로 라우팅
        self.event_bus.subscribe(EventType.PRICE_UPDATED, self._on_price_updated)
        # 시그널 → 주문 매니저로 라우팅
        self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self.order_manager.on_signal)
        # 체결 → 포지션 업데이트
        self.event_bus.subscribe(EventType.ORDER_FILLED, self.position_manager.on_order_filled)

    async def _on_price_updated(self, event: Event) -> None:
        for strategy in self._strategies:
            await strategy.on_tick(event, self.event_bus)

    async def _heartbeat(self) -> None:
        while self._running:
            await asyncio.sleep(60)
            logger.debug("Engine heartbeat")
