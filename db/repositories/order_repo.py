from __future__ import annotations

from sqlalchemy import select, update

from db.models.order import OrderModel
from db.repositories.base import BaseRepository


class OrderRepository(BaseRepository[OrderModel]):
    model = OrderModel

    async def get_by_order_id(self, order_id: str) -> OrderModel | None:
        result = await self.session.execute(
            select(OrderModel).where(OrderModel.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderModel]:
        stmt = select(OrderModel).where(
            OrderModel.status.in_(["pending", "partially_filled"])
        )
        if symbol:
            stmt = stmt.where(OrderModel.symbol == symbol)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        order_id: str,
        status: str,
        executed_qty: str | None = None,
        executed_price: str | None = None,
        error_msg: str | None = None,
    ) -> None:
        values: dict = {"status": status}
        if executed_qty is not None:
            values["executed_qty"] = executed_qty
        if executed_price is not None:
            values["executed_price"] = executed_price
        if error_msg is not None:
            values["error_msg"] = error_msg
        await self.session.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order_id)
            .values(**values)
        )

    async def get_by_symbol(self, symbol: str, limit: int = 50) -> list[OrderModel]:
        result = await self.session.execute(
            select(OrderModel)
            .where(OrderModel.symbol == symbol)
            .order_by(OrderModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
