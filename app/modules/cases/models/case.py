import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.modules.complaints.models.complaint import Complaint
from app.modules.identity.models.user import Department, User


class Case(Base, UUIDMixin, TimestampMixin):
    """Core grievance case grouping one or more citizen complaints."""

    __tablename__ = "cases"

    case_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="TRIAGE_REVIEW", index=True, nullable=False
    )
    priority: Mapped[str] = mapped_column(String(32), default="MEDIUM", index=True, nullable=False)
    lead_department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_officer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    lead_department: Mapped[Optional["Department"]] = relationship(
        "Department", foreign_keys=[lead_department_id]
    )
    assigned_officer: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assigned_officer_id]
    )
    created_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by_id])
    departments: Mapped[list["CaseDepartment"]] = relationship(
        "CaseDepartment", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    case_complaints: Mapped[list["CaseComplaint"]] = relationship(
        "CaseComplaint", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    reassign_requests: Mapped[list["CaseReassignRequest"]] = relationship(
        "CaseReassignRequest", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )


class CaseComplaint(Base, UUIDMixin):
    """Junction table associating complaints with a parent case."""

    __tablename__ = "case_complaints"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    case: Mapped["Case"] = relationship("Case", back_populates="case_complaints")
    complaint: Mapped["Complaint"] = relationship("Complaint")


class CaseDepartment(Base, UUIDMixin):
    """Departments involved in a case with invariant of exactly ONE accountable lead."""

    __tablename__ = "case_departments"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    is_lead: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    added_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    case: Mapped["Case"] = relationship("Case", back_populates="departments")
    department: Mapped["Department"] = relationship("Department")

    __table_args__ = (
        UniqueConstraint("case_id", "department_id", name="uq_case_department"),
        # Partial unique index ensuring exactly ONE lead department per case
        Index(
            "uq_case_lead_department",
            "case_id",
            unique=True,
            postgresql_where=(is_lead.is_(True)),
            sqlite_where=(is_lead == 1),
        ),
    )


class CaseReassignRequest(Base, UUIDMixin):
    """Formal jurisdictional transfer or reassignment requests with audited justifications."""

    __tablename__ = "case_reassign_requests"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    current_department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id"),
        nullable=False,
    )
    suggested_department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True, nullable=False
    )  # PENDING, APPROVED, REJECTED
    decided_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="reassign_requests")
    requested_by: Mapped["User"] = relationship("User", foreign_keys=[requested_by_id])
    current_department: Mapped["Department"] = relationship(
        "Department", foreign_keys=[current_department_id]
    )
    suggested_department: Mapped[Optional["Department"]] = relationship(
        "Department", foreign_keys=[suggested_department_id]
    )
