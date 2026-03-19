"""
PositionManager: 현재 보유 포지션 추적

책임:
    - 주문 체결 이벤트 수신 후 포지션 업데이트
    - 심볼별 평균 매입가 / 수량 추적
    - 미실현 손익 계산
    - 체결마다 PositionModel DB 저장

분리된 책임:
    - 잔고 조회    → portfolio/account.py
    - 주문 실행    → execution/order_manager.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from db.models.position import PositionModel
from db.session import get_session

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
    """심볼별 포지션 상태를 메모리에서 관리하고 DB에 영속화."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    async def on_order_filled(self, event: "Event") -> None:
        """ORDER_FILLED 이벤트 수신 → 포지션 갱신 + DB 저장."""
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

        await self._save_to_db(symbol, side, qty, price, pos)

    async def _save_to_db(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        price: Decimal,
        pos: Position,
    ) -> None:
        try:
            upnl = pos.unrealized_pnl(price) if pos.is_open else Decimal("0")
            async with get_session() as session:
                record = PositionModel(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    avg_price=pos.avg_price,
                    current_qty=pos.quantity,
                    unrealized_pnl=upnl,
                )
                session.add(record)
        except Exception:
            logger.exception("포지션 DB 저장 실패 (무시)")

    def get_position(self, symbol: str) -> Position:
        return self._positions.get(symbol, Position(symbol=symbol))

    def get_all_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if p.is_open}
