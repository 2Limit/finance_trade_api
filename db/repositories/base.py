"""
BaseRepository: DB 접근 캡슐화 기반 클래스

책임:
    - SQLAlchemy AsyncSession 주입
    - 공통 CRUD 메서드 제공 (get, save, delete)
    - 모델별 쿼리 로직을 각 Repository에 집중

사용법:
    class OrderRepository(BaseRepository[OrderModel]):
        model = OrderModel
"""
from __future__ import annotations

from typing import Generic, Type, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    model: Type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()
