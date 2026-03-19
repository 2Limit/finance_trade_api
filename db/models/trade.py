from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TradeModel(Base):
    """실제 체결 내역. OrderModel 체결 시 생성."""

    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_id: Mapped[str] = mapped_column(String(64), index=True)  # FK 역할
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))  # buy | sell
    quantity: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=8))
    price: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=2))
    fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), default=Decimal("0")
    )
    fee_currency: Mapped[str] = mapped_column(String(10), default="KRW")
    strategy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    @property
    def total_value(self) -> Decimal:
        return self.quantity * self.price
