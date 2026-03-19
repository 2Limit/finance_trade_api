from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from db.models.position import PositionModel
from db.repositories.base import BaseRepository


class PositionRepository(BaseRepository[PositionModel]):
    model = PositionModel

    async def get_by_symbol(
        self, symbol: str, limit: int = 50
    ) -> list[PositionModel]:
        result = await self.session.execute(
            select(PositionModel)
            .where(PositionModel.symbol == symbol)
            .order_by(PositionModel.recorded_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_latest(self, symbol: str) -> PositionModel | None:
        result = await self.session.execute(
            select(PositionModel)
            .where(PositionModel.symbol == symbol)
            .order_by(PositionModel.recorded_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_since(
        self, since: datetime, limit: int = 500
    ) -> list[PositionModel]:
        result = await self.session.execute(
            select(PositionModel)
            .where(PositionModel.recorded_at >= since)
            .order_by(PositionModel.recorded_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())
