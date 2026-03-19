"""
E2E 파이프라인 테스트: 전체 흐름 샌드박스 검증

검증 대상:
    PRICE_UPDATED → FeatureBuilder → MACrossoverStrategy
        → SIGNAL_GENERATED → RiskManager → 포지션 업데이트

외부 의존성(Upbit API, Discord)은 모두 Mock 처리.
in-memory SQLite DB 사용.
"""
from __future__ import annotations

import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.event import Event, EventBus, EventType
from data.processor.feature_builder import FeatureBuilder
from db.base import Base
import db.models  # noqa: F401
from db.models.position import PositionModel
from execution.risk import RiskConfig, RiskManager
from market.snapshot import Candle, MarketSnapshot
from portfolio.account import AccountManager
from portfolio.position import PositionManager
from strategy.base import SignalType
from strategy.impl.ma_crossover import MACrossoverStrategy

SYMBOL = "KRW-BTC"
BASE_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


# ── 헬퍼 ────────────────────────────────────────────────────────────────────────

def make_candles_for_golden_cross() -> list[Candle]:
    """
    골든크로스 + RSI 적정 구간(< 70) 동시 만족 패턴.

    구성: 하락(30) → 완만한 상승(40)
    - 하락 구간: RSI 과매도 영역 진입
    - 상승 전환: short SMA 가 long SMA 를 교차할 때 RSI 40~65 수준
    """
    down = [Decimal(str(12000 - i * 80)) for i in range(30)]   # 12000 → 9640
    up = [Decimal(str(9640 + i * 100)) for i in range(40)]     # 9640 → 13540
    prices = down + up
    return [
        Candle(
            symbol=SYMBOL, interval="1m",
            open=p, high=p * Decimal("1.005"),
            low=p * Decimal("0.995"), close=p,
            volume=Decimal("1.0"),
            timestamp=BASE_TIME + timedelta(minutes=i),
        )
        for i, p in enumerate(prices)
    ]


def make_candles_sine(n: int = 120) -> list[Candle]:
    """사인파 캔들 (골든/데드 크로스 반복)."""
    prices = [
        Decimal(str(round(20000 + 5000 * math.sin(2 * math.pi * i / 20), 2)))
        for i in range(n)
    ]
    return [
        Candle(
            symbol=SYMBOL, interval="1m",
            open=p, high=p * Decimal("1.005"),
            low=p * Decimal("0.995"), close=p,
            volume=Decimal("1.0"),
            timestamp=BASE_TIME + timedelta(minutes=i),
        )
        for i, p in enumerate(prices)
    ]


# ── 픽스처 ───────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
def session_factory(engine):
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


# ── 테스트 ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_하락후_상승_골든크로스_BUY_시그널_생성(engine, session_factory):
    """하락 → 상승 전환 캔들 → 골든크로스 발생 시 BUY 시그널 (RSI 적정)."""
    snapshot = MarketSnapshot()
    strategy = MACrossoverStrategy(
        name="e2e_ma",
        symbols=[SYMBOL],
        params={"short_window": 5, "long_window": 20, "rsi_period": 14},
    )
    strategy.set_snapshot(snapshot)
    builder = FeatureBuilder(snapshot=snapshot, short_window=5, long_window=20, rsi_period=14)

    candles = make_candles_for_golden_cross()
    signals = []
    for candle in candles:
        snapshot.update_candle(candle)
        features = builder.build(SYMBOL)
        if features is None:
            continue
        sig = strategy._evaluate(features)
        if sig:
            signals.append(sig)

    # 하락 후 반등 추세에서 BUY 시그널이 1개 이상 발생해야 함
    buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
    assert len(buy_signals) >= 1


@pytest.mark.asyncio
async def test_사인파_여러_시그널_발생(engine, session_factory):
    """사인파 가격 → 골든/데드 크로스 반복 → BUY/SELL 시그널 복수 발생."""
    snapshot = MarketSnapshot()
    strategy = MACrossoverStrategy(
        name="e2e_ma",
        symbols=[SYMBOL],
        params={"short_window": 5, "long_window": 20, "rsi_period": 14},
    )
    strategy.set_snapshot(snapshot)
    builder = FeatureBuilder(snapshot=snapshot, short_window=5, long_window=20, rsi_period=14)

    candles = make_candles_sine(120)
    buy_count = sell_count = 0
    for candle in candles:
        snapshot.update_candle(candle)
        features = builder.build(SYMBOL)
        if features is None:
            continue
        sig = strategy._evaluate(features)
        if sig:
            if sig.signal_type == SignalType.BUY:
                buy_count += 1
            elif sig.signal_type == SignalType.SELL:
                sell_count += 1

    assert buy_count >= 1
    assert sell_count >= 1


@pytest.mark.asyncio
async def test_리스크_통과_포지션_업데이트_E2E(engine, session_factory):
    """
    BUY 시그널 → RiskManager 통과 → PositionManager 업데이트 → DB 저장
    """
    @asynccontextmanager
    async def mock_session():
        async with session_factory() as sess:
            async with sess.begin():
                yield sess

    # 컴포넌트 조립
    event_bus = EventBus()
    position_manager = PositionManager()

    mock_account = MagicMock()
    mock_account.get_available_krw.return_value = Decimal("10000000")
    mock_pos_manager = MagicMock()
    mock_pos_manager.get_position.return_value = MagicMock(
        is_open=False, unrealized_pnl=lambda p: Decimal("0")
    )

    risk_config = RiskConfig(
        max_order_krw=Decimal("500000"),
        max_daily_loss_krw=Decimal("1000000"),
        max_position_ratio=0.3,
    )
    risk = RiskManager(
        config=risk_config,
        account=mock_account,
        position=mock_pos_manager,
        event_bus=event_bus,
    )

    # PositionManager를 ORDER_FILLED 이벤트에 구독
    event_bus.subscribe(EventType.ORDER_FILLED, position_manager.on_order_filled)

    # 리스크 검사
    check_result = await risk.check(
        symbol=SYMBOL,
        side="buy",
        quantity=Decimal("0.005"),
        price=Decimal("90000000"),
    )
    assert check_result.approved is True

    # 주문 체결 이벤트 발행
    with patch("portfolio.position.get_session", mock_session):
        order_event = Event(
            type=EventType.ORDER_FILLED,
            payload={
                "symbol": SYMBOL,
                "side": "buy",
                "quantity": str(check_result.adjusted_qty),
                "price": "90000000",
                "order_id": "e2e-001",
            },
        )
        await event_bus.publish(order_event)

    # 포지션 업데이트 확인
    pos = position_manager.get_position(SYMBOL)
    assert pos.is_open is True
    assert pos.quantity > 0

    # DB 저장 확인
    async with session_factory() as sess:
        from sqlalchemy import select
        result = await sess.execute(select(PositionModel).where(PositionModel.symbol == SYMBOL))
        records = list(result.scalars().all())
    assert len(records) == 1
    assert records[0].side == "buy"


@pytest.mark.asyncio
async def test_계좌_동기화_잔고_이력_DB_저장(engine, session_factory):
    """AccountManager.sync() → BalanceHistoryModel DB 저장."""
    from db.models.balance import BalanceHistoryModel
    from sqlalchemy import select

    mock_broker = MagicMock()
    mock_broker.get_balances = AsyncMock(
        return_value={"KRW": Decimal("5000000"), "BTC": Decimal("0.01")}
    )

    @asynccontextmanager
    async def mock_session():
        async with session_factory() as sess:
            async with sess.begin():
                yield sess

    manager = AccountManager(broker=mock_broker)
    with patch("portfolio.account.get_session", mock_session):
        await manager.sync()

    # KRW 잔고 확인
    assert manager.get_available_krw() == Decimal("5000000")

    # DB 저장 확인
    async with session_factory() as sess:
        result = await sess.execute(select(BalanceHistoryModel))
        records = list(result.scalars().all())
    assert len(records) == 2  # KRW + BTC
    currencies = {r.currency for r in records}
    assert "KRW" in currencies
    assert "BTC" in currencies
