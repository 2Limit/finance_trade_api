"""
공통 pytest fixture.

모든 unit test는 DB / 네트워크 없이 실행된다.
외부 의존성은 MagicMock으로 대체.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from market.snapshot import Candle, MarketSnapshot, Tick


# ── 기본 상수 ──────────────────────────────────────────────────────────────────

SYMBOL = "KRW-BTC"
BASE_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


# ── 가격 데이터 생성 헬퍼 ────────────────────────────────────────────────────────

def make_prices(n: int, start: float = 10000.0, step: float = 100.0) -> list[Decimal]:
    """단조 증가 가격 리스트 생성."""
    return [Decimal(str(start + i * step)) for i in range(n)]


def make_oscillating_prices(n: int, base: float = 10000.0, amplitude: float = 500.0) -> list[Decimal]:
    """골든/데드크로스를 만들 수 있는 사인파 가격."""
    import math
    return [
        Decimal(str(round(base + amplitude * math.sin(2 * math.pi * i / 20), 2)))
        for i in range(n)
    ]


def make_candles(
    prices: list[Decimal],
    symbol: str = SYMBOL,
    interval: str = "1m",
    base_time: datetime = BASE_TIME,
) -> list[Candle]:
    return [
        Candle(
            symbol=symbol,
            interval=interval,
            open=p,
            high=p * Decimal("1.01"),
            low=p * Decimal("0.99"),
            close=p,
            volume=Decimal("1.0"),
            timestamp=base_time + timedelta(minutes=i),
        )
        for i, p in enumerate(prices)
    ]


# ── pytest fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def symbol() -> str:
    return SYMBOL


@pytest.fixture
def base_time() -> datetime:
    return BASE_TIME


@pytest.fixture
def rising_prices() -> list[Decimal]:
    """단조 증가 (골든크로스 유도)."""
    return make_prices(60, start=10000.0, step=200.0)


@pytest.fixture
def falling_prices() -> list[Decimal]:
    """단조 감소 (데드크로스 유도)."""
    return make_prices(60, start=30000.0, step=-200.0)


@pytest.fixture
def oscillating_prices() -> list[Decimal]:
    """골든/데드크로스가 반복되는 가격."""
    return make_oscillating_prices(80, base=20000.0, amplitude=3000.0)


@pytest.fixture
def snapshot_with_candles(symbol: str, rising_prices: list[Decimal]) -> MarketSnapshot:
    """캔들 50개가 채워진 MarketSnapshot."""
    snapshot = MarketSnapshot()
    for candle in make_candles(rising_prices[:50], symbol=symbol):
        snapshot.update_candle(candle)
    return snapshot


@pytest.fixture
def snapshot_empty() -> MarketSnapshot:
    return MarketSnapshot()


@pytest.fixture
def mock_broker() -> MagicMock:
    broker = MagicMock()
    broker.get_balances = AsyncMock(return_value={"KRW": Decimal("1000000"), "BTC": Decimal("0")})
    broker.get_balance = AsyncMock(return_value=Decimal("1000000"))
    broker.place_order = AsyncMock()
    broker.cancel_order = AsyncMock(return_value=True)
    return broker


@pytest.fixture
def mock_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.subscribe = MagicMock()
    return bus
