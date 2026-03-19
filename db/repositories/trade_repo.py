from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from db.models.trade import TradeModel
from db.repositories.base import BaseRepository


class TradeRepository(BaseRepository[TradeModel]):
    model = TradeModel

    async def get_by_symbol(self, symbol: str, limit: int = 100) -> list[TradeModel]:
        result = await self.session.execute(
            select(TradeModel)
            .where(TradeModel.symbol == symbol)
            .order_by(TradeModel.executed_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent(self, limit: int = 50) -> list[TradeModel]:
        result = await self.session.execute(
            select(TradeModel).order_by(TradeModel.executed_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get_daily_pnl(self, date: datetime) -> dict:
        """특정 날짜의 매수/매도 합계 조회 (손익 계산용)."""
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        result = await self.session.execute(
            select(
                TradeModel.side,
                func.sum(TradeModel.quantity * TradeModel.price).label("total_value"),
                func.sum(TradeModel.fee).label("total_fee"),
            )
            .where(TradeModel.executed_at.between(start, end))
            .group_by(TradeModel.side)
        )
        rows = result.all()
        return {row.side: {"value": row.total_value, "fee": row.total_fee} for row in rows}
