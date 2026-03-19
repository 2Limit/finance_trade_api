from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from db.models.balance import BalanceHistoryModel
from db.repositories.base import BaseRepository


class BalanceRepository(BaseRepository[BalanceHistoryModel]):
    model = BalanceHistoryModel

    async def get_by_currency(
        self, currency: str, limit: int = 100
    ) -> list[BalanceHistoryModel]:
        result = await self.session.execute(
            select(BalanceHistoryModel)
            .where(BalanceHistoryModel.currency == currency.upper())
            .order_by(BalanceHistoryModel.recorded_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_latest(self, currency: str) -> BalanceHistoryModel | None:
        result = await self.session.execute(
            select(BalanceHistoryModel)
            .where(BalanceHistoryModel.currency == currency.upper())
            .order_by(BalanceHistoryModel.recorded_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_since(
        self, since: datetime, currency: str | None = None
    ) -> list[BalanceHistoryModel]:
        stmt = select(BalanceHistoryModel).where(
            BalanceHistoryModel.recorded_at >= since
        )
        if currency:
            stmt = stmt.where(
                BalanceHistoryModel.currency == currency.upper()
            )
        stmt = stmt.order_by(BalanceHistoryModel.recorded_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
