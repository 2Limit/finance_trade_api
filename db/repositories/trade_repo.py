"""
TradeRepository: 체결 내역 DB 접근 레이어

책임:
    - 체결 내역 저장
    - 심볼별 / 기간별 체결 조회
    - 수익률 계산을 위한 데이터 제공
"""
from __future__ import annotations

from db.repositories.base import BaseRepository
from db.models.trade import TradeModel  # 구현 예정


class TradeRepository(BaseRepository["TradeModel"]):
    model = "TradeModel"  # type: ignore[assignment]

    async def get_trades_by_symbol(self, symbol: str, limit: int = 100) -> list["TradeModel"]:
        raise NotImplementedError

    async def get_recent_trades(self, limit: int = 50) -> list["TradeModel"]:
        raise NotImplementedError
