"""
통합 테스트: on_tick() → DB 저장 흐름

검증:
    - 캔들 수신 → CandleModel DB 저장
    - 중복 캔들 무시 (UniqueConstraint)
    - MarketSnapshot 상태 동기화
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from data.collector.market_collector import MarketCollector
from db.models.market import CandleModel
from db.repositories.base import BaseRepository
from market.snapshot import Candle, MarketSnapshot


SYMBOL = "KRW-BTC"
BASE_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


class CandleRepository(BaseRepository[CandleModel]):
    model = CandleModel


@pytest.mark.asyncio
async def test_캔들_수집_후_DB_저장(db_engine, db_session, mock_broker):
    """MarketCollector.collect_candles() → CandleModel DB 저장."""
    candles = [
        {
            "market": SYMBOL,
            "candle_date_time_utc": (BASE_TIME + timedelta(minutes=i)).isoformat(),
            "opening_price": 90000000.0,
            "high_price": 91000000.0,
            "low_price": 89000000.0,
            "trade_price": 90000000.0 + i * 100000,
            "candle_acc_trade_volume": 1.0,
        }
        for i in range(5)
    ]
    mock_broker.get_candles = pytest_asyncio.fixture(lambda *a, **kw: candles)
    from unittest.mock import AsyncMock
    mock_broker.get_candles = AsyncMock(return_value=candles)

    snapshot = MarketSnapshot()

    # DB 세션을 주입할 수 있도록 get_session 패치
    from unittest.mock import patch, MagicMock
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_session():
        yield db_session

    with patch("data.collector.market_collector.get_session", mock_get_session):
        collector = MarketCollector(
            client=mock_broker,
            snapshot=snapshot,
            symbols=[SYMBOL],
            interval=1,
        )
        await collector.collect_candles()

    # DB에 저장됐는지 확인
    result = await db_session.execute(select(CandleModel).where(CandleModel.symbol == SYMBOL))
    saved = list(result.scalars().all())
    assert len(saved) == 5
    assert all(c.symbol == SYMBOL for c in saved)


@pytest.mark.asyncio
async def test_중복_캔들_저장_방지(db_engine, db_session, mock_broker):
    """동일 타임스탬프 캔들 2번 수집 → DB 중복 없음."""
    single_candle = [{
        "market": SYMBOL,
        "candle_date_time_utc": BASE_TIME.isoformat(),
        "opening_price": 90000000.0,
        "high_price": 91000000.0,
        "low_price": 89000000.0,
        "trade_price": 90000000.0,
        "candle_acc_trade_volume": 1.0,
    }]
    from unittest.mock import AsyncMock, patch
    from contextlib import asynccontextmanager

    mock_broker.get_candles = AsyncMock(return_value=single_candle)
    snapshot = MarketSnapshot()

    @asynccontextmanager
    async def mock_get_session():
        yield db_session

    collector = MarketCollector(
        client=mock_broker,
        snapshot=snapshot,
        symbols=[SYMBOL],
        interval=1,
    )

    with patch("data.collector.market_collector.get_session", mock_get_session):
        await collector.collect_candles()
        await collector.collect_candles()  # 동일 데이터 2번째 수집

    result = await db_session.execute(select(CandleModel))
    saved = list(result.scalars().all())
    # 중복 저장 방지 → 1개만
    assert len(saved) <= 1


@pytest.mark.asyncio
async def test_스냅샷_업데이트_확인(mock_broker):
    """캔들 수집 후 MarketSnapshot 에 데이터가 들어있어야 한다."""
    from unittest.mock import AsyncMock, patch
    from contextlib import asynccontextmanager
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from db.base import Base
    import db.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    candles_data = [{
        "market": SYMBOL,
        "candle_date_time_utc": BASE_TIME.isoformat(),
        "opening_price": 90000000.0,
        "high_price": 91000000.0,
        "low_price": 89000000.0,
        "trade_price": 90500000.0,
        "candle_acc_trade_volume": 0.5,
    }]
    mock_broker.get_candles = AsyncMock(return_value=candles_data)
    snapshot = MarketSnapshot()

    @asynccontextmanager
    async def mock_session():
        async with factory() as sess:
            async with sess.begin():
                yield sess

    collector = MarketCollector(
        client=mock_broker,
        snapshot=snapshot,
        symbols=[SYMBOL],
        interval=1,
    )
    with patch("data.collector.market_collector.get_session", mock_session):
        await collector.collect_candles()

    candles_in_snapshot = snapshot.get_candles(SYMBOL, limit=10)
    assert len(candles_in_snapshot) == 1
    assert candles_in_snapshot[0].close == Decimal("90500000.0")
    await engine.dispose()
