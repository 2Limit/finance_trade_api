from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PositionModel(Base):
    """포지션 이벤트 이력. 매수/매도 체결마다 스냅샷 기록."""

    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))          # buy | sell
    quantity: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=8))
    avg_price: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=2))
    current_qty: Mapped[Decimal] = mapped_column(          # 체결 후 보유 수량
        Numeric(precision=30, scale=8)
    )
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=20, scale=2), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
