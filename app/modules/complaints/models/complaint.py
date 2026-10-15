import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDMixin


class Ward(Base, UUIDMixin):
    __tablename__ = "wards"

    ward_number: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    boundary_geojson: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=False,
    )
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)


class Complaint(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "complaints"

    tracking_number: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False
    )
    citizen_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    original_title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_description: Mapped[str] = mapped_column(Text, nullable=False)
    original_language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    translated_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    translated_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)

    ward_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("wards.id", ondelete="SET NULL"),
        nullable=True,
    )
    ward_name: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="WEB", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="SUBMITTED", index=True, nullable=False)

    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment", back_populates="complaint", cascade="all", lazy="selectin"
    )


class Attachment(Base, UUIDMixin):
    __tablename__ = "attachments"

    complaint_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    case_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    resolution_proposal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("resolution_proposals.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    challenge_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("citizen_challenges.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attachment_type: Mapped[str] = mapped_column(
        String(32), default="CITIZEN_SUBMISSION", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    complaint: Mapped[Optional["Complaint"]] = relationship(
        "Complaint", back_populates="attachments"
    )
