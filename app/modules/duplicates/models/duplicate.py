import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.modules.complaints.models.complaint import Complaint
from app.modules.identity.models.user import User


class ComplaintEmbedding(Base, UUIDMixin):
    """Vector embedding for complaint text, supporting pgvector in PostgreSQL and fallback JSON."""

    __tablename__ = "complaint_embeddings"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    complaint: Mapped["Complaint"] = relationship("Complaint")


class DuplicateCandidate(Base, UUIDMixin, TimestampMixin):
    """Ranked potential duplicate incident pair with detailed similarity breakdown."""

    __tablename__ = "duplicate_candidates"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    candidate_complaint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    geo_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    semantic_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    category_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    time_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    distance_meters: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True, nullable=False
    )  # PENDING, LINKED, DISMISSED
    decided_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    complaint: Mapped["Complaint"] = relationship("Complaint", foreign_keys=[complaint_id])
    candidate_complaint: Mapped["Complaint"] = relationship(
        "Complaint", foreign_keys=[candidate_complaint_id]
    )
    decided_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[decided_by_id])


class ComplaintSupport(Base, UUIDMixin):
    """Citizen endorsements ('This is the same issue') supporting an existing complaint."""

    __tablename__ = "complaint_supports"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    citizen_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    complaint: Mapped["Complaint"] = relationship("Complaint")
    citizen: Mapped["User"] = relationship("User")

    __table_args__ = (
        UniqueConstraint("complaint_id", "citizen_id", name="uq_complaint_citizen_support"),
    )
