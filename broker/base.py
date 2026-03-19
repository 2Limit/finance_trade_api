"""
AbstractBroker: 주문 실행 브로커 인터페이스

책임:
    - 매수/매도/취소 주문 실행 (REST)
    - 주문 상태 조회
    - 계좌 잔고 조회

분리된 책임:
    - 실시간 가격 피드 → market/feed.py (WebSocket)
    - 계좌/포지션 추적 → portfolio/
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None  # LIMIT 주문 시 필수


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: OrderSide
    status: str
    executed_qty: Decimal
    executed_price: Decimal


class AbstractBroker(ABC):
    """브로커 추상 인터페이스. 거래소마다 구현체를 작성한다."""

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def get_order(self, order_id: str) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    async def get_balance(self, currency: str) -> Decimal:
        """특정 통화 잔고 조회."""
        raise NotImplementedError

    @abstractmethod
    async def get_balances(self) -> dict[str, Decimal]:
        """전체 잔고 조회."""
        raise NotImplementedError
