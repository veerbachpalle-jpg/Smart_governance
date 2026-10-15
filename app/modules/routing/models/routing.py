import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.modules.identity.models.user import Department


class RoutingRule(Base, UUIDMixin, TimestampMixin):
    """Admin-configurable versioned routing rules mapping categories to departments."""

    __tablename__ = "routing_rules"

    rule_version: Mapped[int] = mapped_column(Integer, default=1, index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    sub_category: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    ward_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("wards.id", ondelete="SET NULL"),
        nullable=True,
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    priority_override: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    department: Mapped["Department"] = relationship("Department")


class RoutingRecommendation(Base, UUIDMixin, TimestampMixin):
    """Stores generated routing recommendations pending human officer decision."""

    __tablename__ = "routing_recommendations"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    rule_version_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    primary_department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Ranked list of top-3 departments with confidence and reasons
    recommended_departments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(nullable=False)
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

    primary_department: Mapped["Department"] = relationship("Department")
