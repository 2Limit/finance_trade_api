"""
core/event.py 단위 테스트
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from core.event import Event, EventBus, EventType


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def price_event() -> Event:
    return Event(
        type=EventType.PRICE_UPDATED,
        payload={"symbol": "KRW-BTC", "price": 90000000.0},
    )


class TestEventBus:
    @pytest.mark.asyncio
    async def test_구독_핸들러_호출(self, bus, price_event):
        handler = AsyncMock()
        bus.subscribe(EventType.PRICE_UPDATED, handler)
        await bus.publish(price_event)
        handler.assert_awaited_once_with(price_event)

    @pytest.mark.asyncio
    async def test_여러_핸들러_모두_호출(self, bus, price_event):
        h1 = AsyncMock()
        h2 = AsyncMock()
        bus.subscribe(EventType.PRICE_UPDATED, h1)
        bus.subscribe(EventType.PRICE_UPDATED, h2)
        await bus.publish(price_event)
        h1.assert_awaited_once()
        h2.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_다른_이벤트_타입은_호출_안됨(self, bus, price_event):
        signal_handler = AsyncMock()
        bus.subscribe(EventType.SIGNAL_GENERATED, signal_handler)
        await bus.publish(price_event)  # PRICE_UPDATED 발행
        signal_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_핸들러_없으면_조용히_넘어감(self, bus, price_event):
        """구독자 없는 이벤트 발행 시 예외 없어야 함."""
        await bus.publish(price_event)  # 예외 없음

    @pytest.mark.asyncio
    async def test_핸들러_예외_발생_시_다른_핸들러_계속_호출(self, bus, price_event):
        """하나의 핸들러가 실패해도 나머지 핸들러는 실행되어야 한다."""
        failing = AsyncMock(side_effect=RuntimeError("핸들러 오류"))
        ok_handler = AsyncMock()

        bus.subscribe(EventType.PRICE_UPDATED, failing)
        bus.subscribe(EventType.PRICE_UPDATED, ok_handler)

        await bus.publish(price_event)  # 예외 전파 없음
        ok_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_이벤트_payload_정확히_전달(self, bus):
        received: list[Event] = []

        async def capture(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.ORDER_FILLED, capture)
        event = Event(
            type=EventType.ORDER_FILLED,
            payload={"order_id": "abc123", "symbol": "KRW-BTC", "price": "90000000"},
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].payload["order_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_이벤트에_타임스탬프_자동_부여(self):
        event = Event(type=EventType.PRICE_UPDATED, payload={})
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)

    def test_subscribe는_중복_등록_가능(self, bus):
        handler = AsyncMock()
        bus.subscribe(EventType.PRICE_UPDATED, handler)
        bus.subscribe(EventType.PRICE_UPDATED, handler)
        # 내부 리스트에 2번 등록됨 (의도적 중복 허용)
        assert len(bus._handlers[EventType.PRICE_UPDATED]) == 2
