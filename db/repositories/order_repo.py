"""
OrderRepository: 주문 DB 접근 레이어

책임:
    - 주문 저장 / 상태 업데이트
    - 심볼별 / 상태별 주문 조회
    - execution/ 모듈만 이 Repository를 사용
"""
from __future__ import annotations

from db.repositories.base import BaseRepository
from db.models.order import OrderModel  # 구현 예정


class OrderRepository(BaseRepository["OrderModel"]):
    model = "OrderModel"  # type: ignore[assignment]  # 모델 구현 후 교체

    async def get_by_order_id(self, order_id: str) -> "OrderModel | None":
        raise NotImplementedError

    async def get_open_orders(self, symbol: str) -> list["OrderModel"]:
        raise NotImplementedError

    async def update_status(self, order_id: str, status: str) -> None:
        raise NotImplementedError
