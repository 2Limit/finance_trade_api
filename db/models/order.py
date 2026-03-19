from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrderModel(Base):
    """주문 레코드. 요청~체결~취소 전 생애주기를 추적."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))        # buy | sell
    order_type: Mapped[str] = mapped_column(String(10))  # market | limit
    quantity: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=8))
    price: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=20, scale=2), nullable=True
    )
    executed_qty: Mapped[Decimal] = mapped_column(
        Numeric(precision=30, scale=8), default=Decimal("0")
    )
    executed_price: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=20, scale=2), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | filled | partially_filled | cancelled | failed
    strategy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
