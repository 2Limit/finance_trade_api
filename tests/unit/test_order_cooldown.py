"""
OrderManager 쿨다운(중복 주문 방지) 단위 테스트

검증 대상:
    - 첫 주문은 정상 통과
    - 쿨다운 내 동일 심볼 재주문 스킵
    - 쿨다운 만료 후 주문 통과
    - 다른 심볼은 쿨다운 공유 안 함
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event import Event, EventBus, EventType
from execution.order_manager import OrderManager
from strategy.base import SignalType


def _make_signal_event(symbol: str, signal: str, price: str) -> Event:
    return Event(
        type=EventType.SIGNAL_GENERATED,
        payload={"symbol": symbol, "signal": signal, "price": price, "strategy": "test"},
    )


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    result = MagicMock()
    result.order_id = "ord-001"
    result.status = "done"
    result.executed_qty = Decimal("0.001")
    result.executed_price = Decimal("90000000")
    result.symbol = "KRW-BTC"
    result.side = MagicMock()
    result.side.value = "buy"
    broker.place_order = AsyncMock(return_value=result)
    return broker


@pytest.fixture
def mock_risk():
    risk = MagicMock()
    result = MagicMock()
    result.approved = True
    result.adjusted_qty = None
    result.reason = ""
    risk.check = AsyncMock(return_value=result)
    return result, risk


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def order_manager(mock_broker, mock_risk, event_bus):
    _, risk = mock_risk
    return OrderManager(
        broker=mock_broker,
        risk=risk,
        event_bus=event_bus,
        default_order_krw=Decimal("100000"),
        order_cooldown_sec=60,
    )


@pytest.mark.asyncio
async def test_첫_주문_정상_통과(order_manager, mock_broker):
    """쿨다운 상태 없을 때 첫 주문은 broker.place_order 호출."""
    with patch("execution.order_manager.get_session") as mock_sess:
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)
        event = _make_signal_event("KRW-BTC", SignalType.BUY.value, "90000000")
        await order_manager.on_signal(event)

    mock_broker.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_쿨다운_내_재주문_스킵(order_manager, mock_broker):
    """60초 쿨다운 내 동일 심볼 두 번째 주문 → broker 호출 없음."""
    with patch("execution.order_manager.get_session") as mock_sess:
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)
        event = _make_signal_event("KRW-BTC", SignalType.BUY.value, "90000000")
        await order_manager.on_signal(event)
        await order_manager.on_signal(event)  # 쿨다운 내 재시도

    mock_broker.place_order.assert_called_once()  # 1회만 호출


@pytest.mark.asyncio
async def test_쿨다운_만료_후_주문_통과(order_manager, mock_broker):
    """쿨다운 시간 조작 후 → 주문 재통과."""
    with patch("execution.order_manager.get_session") as mock_sess:
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)
        event = _make_signal_event("KRW-BTC", SignalType.BUY.value, "90000000")
        await order_manager.on_signal(event)

        # 쿨다운 시간을 과거로 조작
        order_manager._last_order_time["KRW-BTC"] = datetime.now(timezone.utc) - timedelta(seconds=61)

        await order_manager.on_signal(event)

    assert mock_broker.place_order.call_count == 2


@pytest.mark.asyncio
async def test_다른_심볼_쿨다운_독립(order_manager, mock_broker):
    """KRW-BTC 쿨다운 중에도 KRW-ETH는 정상 주문 가능."""
    with patch("execution.order_manager.get_session") as mock_sess:
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        btc_event = _make_signal_event("KRW-BTC", SignalType.BUY.value, "90000000")
        eth_event = _make_signal_event("KRW-ETH", SignalType.BUY.value, "5000000")

        await order_manager.on_signal(btc_event)
        await order_manager.on_signal(btc_event)  # 스킵
        await order_manager.on_signal(eth_event)  # 다른 심볼 — 정상 통과

    assert mock_broker.place_order.call_count == 2  # BTC 1회 + ETH 1회
