from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemLogModel(Base):
    """시스템 이벤트 및 에러 로그. 운영 추적용."""

    __tablename__ = "system_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    level: Mapped[str] = mapped_column(String(10))   # INFO | WARNING | ERROR
    event: Mapped[str] = mapped_column(String(100))  # engine.start, risk.triggered 등
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
