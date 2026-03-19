"""
통합 테스트: 주문 실행 → 포지션 업데이트 흐름

검증:
    - ORDER_FILLED 이벤트 수신 → PositionManager.on_order_filled()
    - 매수 후 포지션 보유 확인
    - 매도 후 포지션 청산 확인
    - 매수/매도 체결 후 PositionModel DB 저장 확인
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch, AsyncMock
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from core.event import Event, EventType
from db.base import Base
import db.models  # noqa: F401
from db.models.position import PositionModel
from portfolio.position import PositionManager


SYMBOL = "KRW-BTC"


def make_order_event(side: str, qty: str, price: str) -> Event:
    return Event(
        type=EventType.ORDER_FILLED,
        payload={
            "symbol": SYMBOL,
            "side": side,
            "quantity": qty,
            "price": price,
            "order_id": "test-001",
        },
    )


@pytest.mark.asyncio
async def test_매수_후_포지션_인메모리_보유():
    """DB 없이 인메모리 포지션 업데이트 검증."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def mock_session():
        async with factory() as sess:
            async with sess.begin():
                yield sess

    manager = PositionManager()
    with patch("portfolio.position.get_session", mock_session):
        await manager.on_order_filled(make_order_event("buy", "0.001", "90000000"))

    pos = manager.get_position(SYMBOL)
    assert pos.is_open is True
    assert pos.quantity == Decimal("0.001")
    assert pos.avg_price == Decimal("90000000")
    await engine.dispose()


@pytest.mark.asyncio
async def test_매도_후_포지션_청산():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def mock_session():
        async with factory() as sess:
            async with sess.begin():
                yield sess

    manager = PositionManager()
    with patch("portfolio.position.get_session", mock_session):
        await manager.on_order_filled(make_order_event("buy", "0.001", "90000000"))
        await manager.on_order_filled(make_order_event("sell", "0.001", "95000000"))

    pos = manager.get_position(SYMBOL)
    assert pos.is_open is False
    assert pos.quantity == Decimal("0")
    await engine.dispose()


@pytest.mark.asyncio
async def test_매수_체결_DB_저장():
    """매수 이벤트 처리 후 PositionModel 이 DB에 저장됐는지 확인."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def mock_session():
        async with factory() as sess:
            async with sess.begin():
                yield sess

    manager = PositionManager()
    with patch("portfolio.position.get_session", mock_session):
        await manager.on_order_filled(make_order_event("buy", "0.001", "90000000"))

    async with factory() as sess:
        result = await sess.execute(select(PositionModel).where(PositionModel.symbol == SYMBOL))
        records = list(result.scalars().all())

    assert len(records) == 1
    assert records[0].side == "buy"
    assert records[0].quantity == Decimal("0.001")
    await engine.dispose()


@pytest.mark.asyncio
async def test_추가매수_평균단가_계산():
    """두 번 매수 → 가중 평균단가 계산."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def mock_session():
        async with factory() as sess:
            async with sess.begin():
                yield sess

    manager = PositionManager()
    with patch("portfolio.position.get_session", mock_session):
        await manager.on_order_filled(make_order_event("buy", "1", "90000000"))
        await manager.on_order_filled(make_order_event("buy", "1", "100000000"))

    pos = manager.get_position(SYMBOL)
    assert pos.quantity == Decimal("2")
    # 평균단가: (90M + 100M) / 2 = 95M
    assert pos.avg_price == Decimal("95000000")
    await engine.dispose()
