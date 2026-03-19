"""
EventBus: 컴포넌트 간 이벤트 기반 통신 레이어

흐름:
    MarketFeed → price_updated 이벤트 발행
    Strategy   → signal_generated 이벤트 발행
    Execution  → order_filled 이벤트 발행
    Alert      → 이벤트 구독 후 알림 발송
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class EventType(Enum):
    PRICE_UPDATED = auto()      # 실시간 가격 수신
    CANDLE_CLOSED = auto()      # 캔들 확정
    SIGNAL_GENERATED = auto()   # 전략 시그널 생성
    ORDER_REQUESTED = auto()    # 주문 요청
    ORDER_FILLED = auto()       # 주문 체결
    ORDER_FAILED = auto()       # 주문 실패
    POSITION_CHANGED = auto()   # 포지션 변경
    RISK_TRIGGERED = auto()     # 리스크 한도 초과
    SYSTEM_ERROR = auto()       # 시스템 에러


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)


Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    """비동기 이벤트 버스. 발행/구독 패턴."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed %s to %s", handler.__name__, event_type.name)

    async def publish(self, event: Event) -> None:
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            return
        await asyncio.gather(
            *[self._call(h, event) for h in handlers],
            return_exceptions=True,
        )

    async def _call(self, handler: Handler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception("Handler %s failed for event %s", handler.__name__, event.type.name)
