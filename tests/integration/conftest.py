"""
통합 테스트 공통 픽스처.

실제 DB (aiosqlite in-memory) 사용.
네트워크 의존성(broker, discord)만 Mock 처리.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.base import Base
from market.snapshot import Candle


# ── In-memory DB 픽스처 ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine():
    """테스트용 in-memory SQLite 엔진."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # 모든 모델 임포트(사이드이펙트) 후 테이블 생성
        import db.models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """테스트용 AsyncSession. 각 테스트 후 rollback."""
    factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()


# ── Mock 픽스처 ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.get_balances = AsyncMock(
        return_value={"KRW": Decimal("5000000"), "BTC": Decimal("0")}
    )
    broker.place_order = AsyncMock(return_value=MagicMock(
        order_id="test-order-001",
        symbol="KRW-BTC",
        side="buy",
        quantity=Decimal("0.001"),
        price=Decimal("90000000"),
        status="done",
    ))
    return broker


@pytest.fixture
def mock_alert():
    alert = MagicMock()
    alert.send = AsyncMock()
    alert.on_signal = AsyncMock()
    alert.on_order_filled = AsyncMock()
    alert.on_risk_triggered = AsyncMock()
    return alert


# ── 캔들 헬퍼 ─────────────────────────────────────────────────────────────────

SYMBOL = "KRW-BTC"
BASE_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


def make_candles(prices: list[Decimal], symbol: str = SYMBOL) -> list[Candle]:
    return [
        Candle(
            symbol=symbol,
            interval="1m",
            open=p,
            high=p * Decimal("1.01"),
            low=p * Decimal("0.99"),
            close=p,
            volume=Decimal("1.0"),
            timestamp=BASE_TIME + timedelta(minutes=i),
        )
        for i, p in enumerate(prices)
    ]
