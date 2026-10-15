import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.modules.cases.models.case import Case
from app.modules.identity.models.user import User


class ResolutionProposal(Base, UUIDMixin, TimestampMixin):
    """Formal physical remediation proposal submitted by an officer with verification evidence."""

    __tablename__ = "resolution_proposals"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    proposing_officer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    remediation_summary: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause_identified: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    officer_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    officer_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_window_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), default="PROPOSED", index=True, nullable=False
    )  # PROPOSED, ACCEPTED, CHALLENGED, AUTO_CLOSED

    case: Mapped["Case"] = relationship("Case")
    proposing_officer: Mapped["User"] = relationship("User", foreign_keys=[proposing_officer_id])
    challenges: Mapped[list["CitizenChallenge"]] = relationship(
        "CitizenChallenge",
        back_populates="resolution_proposal",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CitizenChallenge(Base, UUIDMixin, TimestampMixin):
    """Formal dispute filed by a citizen against a proposed resolution, rejection, or action."""

    __tablename__ = "citizen_challenges"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    resolution_proposal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("resolution_proposals.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    citizen_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    challenge_type: Mapped[str] = mapped_column(
        String(32), default="RESOLUTION", index=True, nullable=False
    )  # RESOLUTION, REJECTION, OFFICIAL_ACTION, PRIORITY
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True, nullable=False
    )  # PENDING, UNDER_REVIEW, UPHELD, OVERTURNED
    sla_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    is_escalated: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped["Case"] = relationship("Case")
    citizen: Mapped["User"] = relationship("User", foreign_keys=[citizen_id])
    resolution_proposal: Mapped[Optional["ResolutionProposal"]] = relationship(
        "ResolutionProposal", back_populates="challenges"
    )
    review: Mapped[Optional["ChallengeReview"]] = relationship(
        "ChallengeReview", back_populates="challenge", uselist=False, lazy="selectin"
    )


class ChallengeReview(Base, UUIDMixin, TimestampMixin):
    """Formal review decision executed by a supervisor or independent senior officer."""

    __tablename__ = "challenge_reviews"

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("citizen_challenges.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    verdict: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False
    )  # UPHELD (citizen's dispute justified -> reopens case) or OVERTURNED (challenge denied -> closed)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    challenge: Mapped["CitizenChallenge"] = relationship(
        "CitizenChallenge", back_populates="review"
    )
    reviewer: Mapped["User"] = relationship("User", foreign_keys=[reviewer_id])


class ReopenEvent(Base, UUIDMixin):
    """Immutable audit record documenting the reopening of an overturned or escalated case."""

    __tablename__ = "reopen_events"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trigger_source: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # CHALLENGE_UPHELD, SUPERVISOR_OVERTURN, REOPEN_REQUEST
    challenge_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("citizen_challenges.id", ondelete="SET NULL"),
        nullable=True,
    )
    authorized_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reopened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    case: Mapped["Case"] = relationship("Case")
    authorized_by: Mapped["User"] = relationship("User", foreign_keys=[authorized_by_id])
