from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from core.event import Event, EventBus, EventType

if TYPE_CHECKING:
    from portfolio.account import AccountManager
    from portfolio.position import PositionManager

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    max_order_krw: Decimal        # 단일 주문 최대 금액
    max_daily_loss_krw: Decimal   # 일일 최대 손실 한도
    max_position_ratio: float     # 포트폴리오 대비 최대 포지션 비중 (0~1)


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str = ""
    adjusted_qty: Decimal | None = None  # 금액 초과 시 자동 조정된 수량


class RiskManager:
    """
    주문 실행 전 리스크 검증.

    검증 항목:
        1. 단일 주문 금액 한도
        2. 일일 손실 한도
        3. 포지션 비중 한도

    거부 시 EventBus에 RISK_TRIGGERED 이벤트 발행.
    """

    def __init__(
        self,
        config: RiskConfig,
        account: "AccountManager",
        position: "PositionManager",
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._account = account
        self._position = position
        self._event_bus = event_bus
        self._daily_loss: Decimal = Decimal("0")
        self._loss_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def check(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
    ) -> RiskCheckResult:
        """주문 허용 여부 판단. 거부 시 이유 포함."""
        self._reset_daily_loss_if_needed()

        order_value = quantity * price

        # 1. 단일 주문 금액 한도
        if order_value > self._config.max_order_krw:
            adjusted_qty = (self._config.max_order_krw / price).quantize(Decimal("0.00000001"))
            logger.warning(
                "단일 주문 금액 초과 (%.0f > %.0f KRW). 수량 조정: %s → %s",
                order_value, self._config.max_order_krw, quantity, adjusted_qty
            )
            quantity = adjusted_qty
            order_value = quantity * price

        # 2. 일일 손실 한도
        if side == "sell":
            position = self._position.get_position(symbol)
            if position.is_open:
                unrealized_loss = position.unrealized_pnl(price)
                if unrealized_loss < Decimal("0"):
                    projected_loss = self._daily_loss + abs(unrealized_loss)
                    if projected_loss > self._config.max_daily_loss_krw:
                        reason = (
                            f"일일 손실 한도 초과 예정 "
                            f"(현재={self._daily_loss:.0f}, "
                            f"예상 추가={abs(unrealized_loss):.0f}, "
                            f"한도={self._config.max_daily_loss_krw:.0f} KRW)"
                        )
                        await self._trigger(symbol, reason)
                        return RiskCheckResult(approved=False, reason=reason)

        # 3. 포지션 비중 한도
        if side == "buy":
            available_krw = self._account.get_available_krw()
            total_portfolio = available_krw + order_value  # 단순화된 계산
            position_ratio = float(order_value / total_portfolio) if total_portfolio > 0 else 0
            if position_ratio > self._config.max_position_ratio:
                reason = (
                    f"포지션 비중 한도 초과 "
                    f"({position_ratio:.1%} > {self._config.max_position_ratio:.1%})"
                )
                await self._trigger(symbol, reason)
                return RiskCheckResult(approved=False, reason=reason)

        return RiskCheckResult(approved=True, adjusted_qty=quantity)

    def record_loss(self, amount: Decimal) -> None:
        """체결 후 실현 손실 기록."""
        if amount > 0:
            self._daily_loss += amount
            logger.info("일일 손실 기록: %.2f (누적: %.2f)", amount, self._daily_loss)

    def reset_daily_loss(self) -> None:
        """일일 손실 카운터를 명시적으로 리셋 (스케줄러에서 자정에 호출)."""
        self._daily_loss = Decimal("0")
        self._loss_reset_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logger.info("일일 손실 카운터 명시적 리셋")

    def _reset_daily_loss_if_needed(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._loss_reset_date:
            self.reset_daily_loss()
            logger.info("일일 손실 카운터 자동 초기화")

    async def _trigger(self, symbol: str, reason: str) -> None:
        logger.warning("[RISK] %s | %s", symbol, reason)
        await self._event_bus.publish(
            Event(
                type=EventType.RISK_TRIGGERED,
                payload={"symbol": symbol, "reason": reason},
            )
        )
