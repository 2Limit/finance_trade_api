"""
PositionManager: 현재 보유 포지션 추적

책임:
    - 주문 체결 이벤트 수신 후 포지션 업데이트
    - 심볼별 평균 매입가 / 수량 추적
    - 미실현 손익 계산

분리된 책임:
    - 잔고 조회    → portfolio/account.py
    - 주문 실행    → execution/order_manager.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.event import Event

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    quantity: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")

    @property
    def is_open(self) -> bool:
        return self.quantity > Decimal("0")

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        return (current_price - self.avg_price) * self.quantity


class PositionManager:
    """심볼별 포지션 상태를 메모리에서 관리."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    async def on_order_filled(self, event: "Event") -> None:
        """ORDER_FILLED 이벤트 수신 → 포지션 갱신."""
        payload = event.payload
        symbol: str = payload["symbol"]
        side: str = payload["side"]
        qty: Decimal = Decimal(str(payload["quantity"]))
        price: Decimal = Decimal(str(payload["price"]))

        pos = self._positions.setdefault(symbol, Position(symbol=symbol))

        if side == "buy":
            total_cost = pos.avg_price * pos.quantity + price * qty
            pos.quantity += qty
            pos.avg_price = total_cost / pos.quantity if pos.quantity > 0 else Decimal("0")
        elif side == "sell":
            pos.quantity -= qty
            if pos.quantity <= Decimal("0"):
                pos.quantity = Decimal("0")
                pos.avg_price = Decimal("0")

        logger.info("Position updated: %s qty=%s avg=%s", symbol, pos.quantity, pos.avg_price)

    def get_position(self, symbol: str) -> Position:
        return self._positions.get(symbol, Position(symbol=symbol))

    def get_all_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if p.is_open}
