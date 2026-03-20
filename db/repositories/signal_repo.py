from __future__ import annotations

from sqlalchemy import select

from db.models.signal import SignalModel
from db.repositories.base import BaseRepository


class SignalRepository(BaseRepository[SignalModel]):
    model = SignalModel

    async def get_by_strategy(self, strategy_name: str, limit: int = 100) -> list[SignalModel]:
        result = await self.session.execute(
            select(SignalModel)
            .where(SignalModel.strategy_name == strategy_name)
            .order_by(SignalModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_symbol(self, symbol: str, limit: int = 100) -> list[SignalModel]:
        result = await self.session.execute(
            select(SignalModel)
            .where(SignalModel.symbol == symbol)
            .order_by(SignalModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent(self, limit: int = 50) -> list[SignalModel]:
        result = await self.session.execute(
            select(SignalModel).order_by(SignalModel.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
