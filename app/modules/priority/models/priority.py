import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDMixin


class PriorityPolicy(Base, UUIDMixin, TimestampMixin):
    """Configurable multilingual safety policies that can elevate grievance priority."""

    __tablename__ = "priority_policies"

    policy_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="all", index=True, nullable=False)
    keyword_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    elevate_to_priority: Mapped[str] = mapped_column(
        String(32), default="CRITICAL", nullable=False
    )  # CRITICAL or HIGH
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)


class PriorityAssessment(Base, UUIDMixin, TimestampMixin):
    """Stored priority assessment combining explicit rule hits and model scoring."""

    __tablename__ = "priority_assessments"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    model_priority: Mapped[str] = mapped_column(String(32), nullable=False)
    model_confidence: Mapped[float] = mapped_column(nullable=False)
    model_reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    rule_hits: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=False,
    )
    final_suggested_priority: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False
    )  # CRITICAL, HIGH, MEDIUM, LOW
    suggested_sla_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    is_safety_critical: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, nullable=False
    )
    recommendation_status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True, nullable=False
    )  # PENDING, ACCEPTED, OVERRIDDEN, REJECTED
    decided_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
