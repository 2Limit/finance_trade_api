from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandleModel(Base):
    """OHLCV 캔들 데이터. MarketCollector가 수집."""

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "timestamp", name="uq_candle"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    interval: Mapped[str] = mapped_column(String(10))  # 1m, 5m, 1h, 1d
    open: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=2))
    high: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=2))
    low: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=2))
    close: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=2))
    volume: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=8))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
