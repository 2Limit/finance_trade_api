"""
execution/risk.py 단위 테스트

외부 의존성:
    - AccountManager: MagicMock (잔고 반환)
    - PositionManager: MagicMock (포지션 반환)
    - EventBus: AsyncMock (이벤트 발행 캡처)
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event import EventBus, EventType
from execution.risk import RiskConfig, RiskCheckResult, RiskManager
from portfolio.position import Position, PositionManager


def make_risk_manager(
    max_order_krw: float = 500_000,
    max_daily_loss_krw: float = 1_000_000,
    max_position_ratio: float = 0.3,
    available_krw: float = 10_000_000,
    position: Position | None = None,
) -> tuple[RiskManager, AsyncMock]:
    config = RiskConfig(
        max_order_krw=Decimal(str(max_order_krw)),
        max_daily_loss_krw=Decimal(str(max_daily_loss_krw)),
        max_position_ratio=max_position_ratio,
    )
    account = MagicMock()
    account.get_available_krw.return_value = Decimal(str(available_krw))

    pos_manager = MagicMock(spec=PositionManager)
    pos_manager.get_position.return_value = position or Position(symbol="KRW-BTC")

    bus_publish = AsyncMock()
    bus = MagicMock(spec=EventBus)
    bus.publish = bus_publish

    risk = RiskManager(config=config, account=account, position=pos_manager, event_bus=bus)
    return risk, bus_publish


class TestRiskManager:
    @pytest.mark.asyncio
    async def test_정상_매수_승인(self):
        risk, _ = make_risk_manager()
        result = await risk.check("KRW-BTC", "buy", Decimal("0.001"), Decimal("90000000"))
        assert result.approved is True

    @pytest.mark.asyncio
    async def test_단일_주문_금액_초과_시_수량_자동_조정(self):
        risk, _ = make_risk_manager(max_order_krw=500_000)
        # 주문금액 = 0.01 * 90,000,000 = 900,000 (한도 500,000 초과)
        result = await risk.check("KRW-BTC", "buy", Decimal("0.01"), Decimal("90000000"))
        assert result.approved is True
        assert result.adjusted_qty is not None
        # 조정된 수량 × 가격이 한도에 근접해야 함 (quantize 반올림 허용 +1 KRW)
        adjusted_value = result.adjusted_qty * Decimal("90000000")
        assert adjusted_value <= Decimal("500001")  # 반올림 허용치

    @pytest.mark.asyncio
    async def test_포지션_비중_초과_시_거부(self):
        # available_krw 낮게, 주문금액 크게 → 비중 초과
        risk, publish = make_risk_manager(
            max_order_krw=500_000,
            available_krw=100_000,    # 잔고가 매우 적음
            max_position_ratio=0.1,   # 10% 한도
        )
        # order_value = 0.005 * 90M = 450,000
        # total_portfolio = 100,000 + 450,000 = 550,000
        # ratio = 450,000/550,000 ≈ 81.8% > 10%
        result = await risk.check("KRW-BTC", "buy", Decimal("0.005"), Decimal("90000000"))
        assert result.approved is False
        publish.assert_awaited_once()
        event = publish.call_args[0][0]
        assert event.type == EventType.RISK_TRIGGERED

    @pytest.mark.asyncio
    async def test_일일_손실_한도_초과_시_매도_거부(self):
        # 보유 포지션: 평단 95M, 현재가 90M → 미실현 손실 5M
        position = Position(
            symbol="KRW-BTC",
            quantity=Decimal("1"),
            avg_price=Decimal("95000000"),
        )
        risk, publish = make_risk_manager(
            max_daily_loss_krw=1_000_000,  # 한도 1M
            position=position,
        )
        # 미실현 손실 = 5M > 한도 1M → 거부
        result = await risk.check("KRW-BTC", "sell", Decimal("1"), Decimal("90000000"))
        assert result.approved is False
        publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_포지션_없으면_매도_승인(self):
        # 포지션 없음 → 손실 한도 검사 스킵
        risk, _ = make_risk_manager()
        result = await risk.check("KRW-BTC", "sell", Decimal("0.001"), Decimal("90000000"))
        assert result.approved is True

    @pytest.mark.asyncio
    async def test_이익_포지션_매도는_손실한도_검사_스킵(self):
        position = Position(
            symbol="KRW-BTC",
            quantity=Decimal("1"),
            avg_price=Decimal("80000000"),  # 매수가 낮음 → 이익 중
        )
        risk, _ = make_risk_manager(position=position)
        result = await risk.check("KRW-BTC", "sell", Decimal("1"), Decimal("90000000"))
        assert result.approved is True

    def test_record_loss_누적(self):
        risk, _ = make_risk_manager()
        risk.record_loss(Decimal("100000"))
        risk.record_loss(Decimal("200000"))
        assert risk._daily_loss == Decimal("300000")
