"""
AccountManager: 계좌 잔고 관리

책임:
    - 브로커로부터 잔고 동기화
    - 통화별 가용 잔고 조회
    - 주문 가능 금액 계산
    - sync() 호출마다 잔고 이력 DB 저장

분리된 책임:
    - 포지션 추적 → portfolio/position.py
    - 주문 실행   → execution/order_manager.py
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from db.models.balance import BalanceHistoryModel
from db.session import get_session

if TYPE_CHECKING:
    from broker.base import AbstractBroker

logger = logging.getLogger(__name__)


class AccountManager:
    """계좌 잔고 관리. 브로커 API를 통해 동기화."""

    def __init__(self, broker: "AbstractBroker") -> None:
        self.broker = broker
        self._balances: dict[str, Decimal] = {}

    async def sync(self) -> None:
        """브로커에서 최신 잔고를 가져와 캐시 갱신 후 DB에 이력 저장."""
        self._balances = await self.broker.get_balances()
        logger.debug("Account synced: %s", self._balances)
        await self._save_history()

    async def _save_history(self) -> None:
        if not self._balances:
            return
        try:
            async with get_session() as session:
                for currency, balance in self._balances.items():
                    session.add(BalanceHistoryModel(currency=currency, balance=balance))
        except Exception:
            logger.exception("잔고 이력 DB 저장 실패 (무시)")

    def get_balance(self, currency: str) -> Decimal:
        return self._balances.get(currency.upper(), Decimal("0"))

    def get_available_krw(self) -> Decimal:
        return self.get_balance("KRW")

    def get_all_balances(self) -> dict[str, Decimal]:
        return dict(self._balances)
