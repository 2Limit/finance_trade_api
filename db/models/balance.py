from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BalanceHistoryModel(Base):
    """계좌 잔고 이력. AccountManager.sync() 호출마다 스냅샷 기록."""

    __tablename__ = "balance_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    currency: Mapped[str] = mapped_column(String(10), index=True)   # KRW | BTC ...
    balance: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=8))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
