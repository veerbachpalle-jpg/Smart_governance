from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDMixin


class NotificationLog(Base, UUIDMixin, TimestampMixin):
    """Immutable log of outbound notifications dispatched to citizens or staff."""

    __tablename__ = "notification_logs"

    recipient: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="console", nullable=False)
    notification_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True, nullable=False
    )  # PENDING, SENT, FAILED, DEAD_LETTER
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=True,
    )
