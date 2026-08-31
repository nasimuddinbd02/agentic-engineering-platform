from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.time import utcnow
from persistence.models.types import UtcDateTime


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
