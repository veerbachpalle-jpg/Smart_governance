import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.errors import ConflictError
from app.db.base import Base, UUIDMixin
from app.modules.cases.models.case import Case
from app.modules.complaints.models.complaint import Complaint
from app.modules.identity.models.user import User


class CaseActivity(Base, UUIDMixin):
    """Immutable official history log of all events and state transitions for a case."""

    __tablename__ = "case_activities"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    complaint_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    activity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(32), default="INTERNAL", index=True, nullable=False
    )  # INTERNAL or CITIZEN_VISIBLE
    message: Mapped[str] = mapped_column(Text, nullable=False)
    activity_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    case: Mapped["Case"] = relationship("Case")
    complaint: Mapped[Optional["Complaint"]] = relationship("Complaint")
    actor: Mapped[Optional["User"]] = relationship("User")


class CitizenUpdate(Base, UUIDMixin):
    """Public updates broadcast specifically for citizen tracking."""

    __tablename__ = "citizen_updates"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    case: Mapped["Case"] = relationship("Case")
    author: Mapped["User"] = relationship("User")


# DB-level immutability enforcement: block any UPDATE or DELETE on CaseActivity
@event.listens_for(CaseActivity, "before_update")
def block_case_activity_update(mapper: Any, connection: Any, target: CaseActivity) -> None:
    raise ConflictError(
        "Case activities are strictly append-only. Modification is forbidden by compliance invariants.",
        code="ACTIVITY_IMMUTABLE",
    )


@event.listens_for(CaseActivity, "before_delete")
def block_case_activity_delete(mapper: Any, connection: Any, target: CaseActivity) -> None:
    raise ConflictError(
        "Case activities are strictly append-only. Deletion is forbidden by compliance invariants.",
        code="ACTIVITY_IMMUTABLE",
    )
