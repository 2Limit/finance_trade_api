"""
StopLossMonitor 단위 테스트

검증 대상:
    - 손절 발동 (pnl_pct <= -stop_loss_pct)
    - 익절 발동 (pnl_pct >= take_profit_pct)
    - 중복 발동 방지 (_triggered 세트)
    - 포지션 청산 후 재활성화
    - 포지션 없을 때 무동작
    - 가격 미수신 시 무동작
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event import Event, EventBus, EventType
from execution.stop_loss import StopLossConfig, StopLossMonitor
from strategy.base import SignalType


def _make_position(is_open: bool, avg_price: Decimal, quantity: Decimal, pnl: Decimal) -> MagicMock:
    pos = MagicMock()
    pos.is_open = is_open
    pos.avg_price = avg_price
    pos.quantity = quantity
    pos.unrealized_pnl = MagicMock(return_value=pnl)
    return pos


def _make_event(symbol: str, price: str) -> Event:
    return Event(type=EventType.PRICE_UPDATED, payload={"symbol": symbol, "price": price})


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def config():
    return StopLossConfig(stop_loss_pct=0.05, take_profit_pct=0.10)


@pytest.fixture
def position_manager():
    return MagicMock()


@pytest.fixture
def monitor(config, position_manager, event_bus):
    return StopLossMonitor(config=config, position_manager=position_manager, event_bus=event_bus)


# ── 손절 발동 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_손절_발동_SELL_시그널_발행(monitor, position_manager, event_bus):
    """pnl_pct = -10% → 손절 SELL 발행."""
    avg_price = Decimal("100000")
    qty = Decimal("1")
    cost = avg_price * qty  # 100000
    pnl = Decimal("-10000")  # -10%
    position_manager.get_position.return_value = _make_position(True, avg_price, qty, pnl)

    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    await monitor.on_price_updated(_make_event("KRW-BTC", "90000"))

    assert len(published) == 1
    assert published[0].payload["signal"] == SignalType.SELL.value
    assert published[0].payload["symbol"] == "KRW-BTC"


@pytest.mark.asyncio
async def test_손절_미발동_정상_수익률(monitor, position_manager, event_bus):
    """pnl_pct = -2% → 손절 기준(-5%) 미달, 발행 없음."""
    avg_price = Decimal("100000")
    qty = Decimal("1")
    pnl = Decimal("-2000")  # -2%
    position_manager.get_position.return_value = _make_position(True, avg_price, qty, pnl)

    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    await monitor.on_price_updated(_make_event("KRW-BTC", "98000"))

    assert len(published) == 0


# ── 익절 발동 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_익절_발동_SELL_시그널_발행(monitor, position_manager, event_bus):
    """pnl_pct = +15% → 익절 SELL 발행."""
    avg_price = Decimal("100000")
    qty = Decimal("1")
    pnl = Decimal("15000")  # +15%
    position_manager.get_position.return_value = _make_position(True, avg_price, qty, pnl)

    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    await monitor.on_price_updated(_make_event("KRW-ETH", "115000"))

    assert len(published) == 1
    assert published[0].payload["signal"] == SignalType.SELL.value


@pytest.mark.asyncio
async def test_익절_미발동_낮은_수익률(monitor, position_manager, event_bus):
    """pnl_pct = +5% → 익절 기준(+10%) 미달, 발행 없음."""
    avg_price = Decimal("100000")
    qty = Decimal("1")
    pnl = Decimal("5000")  # +5%
    position_manager.get_position.return_value = _make_position(True, avg_price, qty, pnl)

    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    await monitor.on_price_updated(_make_event("KRW-BTC", "105000"))

    assert len(published) == 0


# ── 중복 발동 방지 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_중복_발동_방지(monitor, position_manager, event_bus):
    """첫 발동 후 동일 심볼에 두 번째 이벤트 → 추가 발행 없음."""
    avg_price = Decimal("100000")
    qty = Decimal("1")
    pnl = Decimal("-10000")
    position_manager.get_position.return_value = _make_position(True, avg_price, qty, pnl)

    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    await monitor.on_price_updated(_make_event("KRW-BTC", "90000"))
    await monitor.on_price_updated(_make_event("KRW-BTC", "89000"))  # 재발동 시도

    assert len(published) == 1  # 최초 1회만


# ── 포지션 청산 후 재활성화 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_포지션_청산_후_재활성화(monitor, position_manager, event_bus):
    """포지션 청산(is_open=False) → _triggered 해제 → 재진입 시 재발동 가능."""
    avg_price = Decimal("100000")
    qty = Decimal("1")
    pnl = Decimal("-10000")

    open_pos = _make_position(True, avg_price, qty, pnl)
    closed_pos = _make_position(False, avg_price, Decimal("0"), Decimal("0"))

    position_manager.get_position.return_value = open_pos

    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    # 1차 발동
    await monitor.on_price_updated(_make_event("KRW-BTC", "90000"))
    assert len(published) == 1

    # 포지션 청산 이벤트 시뮬레이션
    position_manager.get_position.return_value = closed_pos
    await monitor.on_price_updated(_make_event("KRW-BTC", "90000"))

    # 재진입 후 다시 발동
    position_manager.get_position.return_value = open_pos
    await monitor.on_price_updated(_make_event("KRW-BTC", "89000"))
    assert len(published) == 2


# ── 예외 케이스 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_포지션_없을_때_무동작(monitor, position_manager, event_bus):
    """포지션이 없을 때(is_open=False) 시그널 미발행."""
    position_manager.get_position.return_value = _make_position(
        False, Decimal("0"), Decimal("0"), Decimal("0")
    )

    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    await monitor.on_price_updated(_make_event("KRW-BTC", "90000"))

    assert len(published) == 0


@pytest.mark.asyncio
async def test_가격_미수신_무동작(monitor, position_manager, event_bus):
    """payload에 price가 없으면 무동작."""
    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    event = Event(type=EventType.PRICE_UPDATED, payload={"symbol": "KRW-BTC"})
    await monitor.on_price_updated(event)

    assert len(published) == 0
    position_manager.get_position.assert_not_called()


@pytest.mark.asyncio
async def test_심볼_미수신_무동작(monitor, position_manager, event_bus):
    """payload에 symbol이 없으면 무동작."""
    published = []
    event_bus.subscribe(EventType.SIGNAL_GENERATED, lambda e: published.append(e))

    event = Event(type=EventType.PRICE_UPDATED, payload={"price": "90000"})
    await monitor.on_price_updated(event)

    assert len(published) == 0
