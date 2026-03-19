"""
통합 테스트: 리스크 검사 → RISK_TRIGGERED 이벤트 → 알림 발행 흐름

검증:
    - 포지션 비중 초과 시 RISK_TRIGGERED 이벤트 발행
    - 일일 손실 한도 초과 시 RISK_TRIGGERED 이벤트 발행
    - EventBus 구독 핸들러(alert.on_risk_triggered) 실제 호출 확인
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event import Event, EventBus, EventType
from execution.risk import RiskConfig, RiskManager
from portfolio.account import AccountManager
from portfolio.position import PositionManager, Position


def make_risk_manager(
    max_order_krw: float = 500_000,
    max_daily_loss_krw: float = 1_000_000,
    max_position_ratio: float = 0.3,
    available_krw: float = 10_000_000,
    position: Position | None = None,
) -> tuple[RiskManager, EventBus, AsyncMock]:
    config = RiskConfig(
        max_order_krw=Decimal(str(max_order_krw)),
        max_daily_loss_krw=Decimal(str(max_daily_loss_krw)),
        max_position_ratio=max_position_ratio,
    )
    account = MagicMock()
    account.get_available_krw.return_value = Decimal(str(available_krw))

    pos_manager = MagicMock(spec=PositionManager)
    pos_manager.get_position.return_value = position or Position(symbol="KRW-BTC")

    bus = EventBus()
    risk_handler = AsyncMock()
    bus.subscribe(EventType.RISK_TRIGGERED, risk_handler)

    risk = RiskManager(config=config, account=account, position=pos_manager, event_bus=bus)
    return risk, bus, risk_handler


@pytest.mark.asyncio
async def test_포지션_비중_초과_이벤트_핸들러_호출():
    """비중 초과 시 RISK_TRIGGERED 이벤트 → 구독 핸들러 실제 호출."""
    risk, bus, handler = make_risk_manager(
        available_krw=100_000,
        max_position_ratio=0.1,
    )
    result = await risk.check("KRW-BTC", "buy", Decimal("0.005"), Decimal("90000000"))

    assert result.approved is False
    handler.assert_awaited_once()
    event: Event = handler.call_args[0][0]
    assert event.type == EventType.RISK_TRIGGERED
    assert "KRW-BTC" in str(event.payload)


@pytest.mark.asyncio
async def test_일일_손실_한도_초과_이벤트_발행():
    """미실현 손실 > 한도 시 RISK_TRIGGERED."""
    position = Position(
        symbol="KRW-BTC",
        quantity=Decimal("1"),
        avg_price=Decimal("95000000"),
    )
    risk, bus, handler = make_risk_manager(
        max_daily_loss_krw=1_000_000,
        position=position,
    )
    result = await risk.check("KRW-BTC", "sell", Decimal("1"), Decimal("90000000"))

    assert result.approved is False
    handler.assert_awaited_once()
    event: Event = handler.call_args[0][0]
    assert event.type == EventType.RISK_TRIGGERED
    assert "손실" in event.payload.get("reason", "")


@pytest.mark.asyncio
async def test_정상_주문은_이벤트_미발행():
    """정상 범위 주문 → RISK_TRIGGERED 이벤트 없음."""
    risk, bus, handler = make_risk_manager()
    result = await risk.check("KRW-BTC", "buy", Decimal("0.001"), Decimal("90000000"))

    assert result.approved is True
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_daily_loss_후_손실한도_재적용():
    """reset_daily_loss() 후 동일 조건에서 손실 한도 리셋 확인."""
    position = Position(
        symbol="KRW-BTC",
        quantity=Decimal("1"),
        avg_price=Decimal("95000000"),
    )
    risk, bus, handler = make_risk_manager(
        max_daily_loss_krw=1_000_000,
        position=position,
    )
    # 첫 번째: 거부
    result1 = await risk.check("KRW-BTC", "sell", Decimal("1"), Decimal("90000000"))
    assert result1.approved is False

    # 리셋 후 동일 조건 → 여전히 거부 (미실현 손실 자체가 한도 초과)
    risk.reset_daily_loss()
    assert risk._daily_loss == Decimal("0")


@pytest.mark.asyncio
async def test_이벤트버스_멀티_핸들러_모두_호출():
    """RISK_TRIGGERED 이벤트에 복수 핸들러 등록 시 모두 호출."""
    risk, bus, handler1 = make_risk_manager(
        available_krw=100_000,
        max_position_ratio=0.1,
    )
    handler2 = AsyncMock()
    bus.subscribe(EventType.RISK_TRIGGERED, handler2)

    await risk.check("KRW-BTC", "buy", Decimal("0.005"), Decimal("90000000"))

    handler1.assert_awaited_once()
    handler2.assert_awaited_once()
