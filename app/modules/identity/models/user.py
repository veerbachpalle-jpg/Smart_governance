import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    citizen_profile: Mapped[Optional["CitizenProfile"]] = relationship(
        "CitizenProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    department_memberships: Mapped[list["DepartmentMember"]] = relationship(
        "DepartmentMember",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class CitizenProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "citizen_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    notification_preference: Mapped[str] = mapped_column(
        String(32), default="email", nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="citizen_profile")


class Department(Base, UUIDMixin):
    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    members: Mapped[list["DepartmentMember"]] = relationship(
        "DepartmentMember",
        back_populates="department",
        cascade="all, delete-orphan",
    )


class DepartmentMember(Base, UUIDMixin):
    __tablename__ = "department_members"

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_role: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # lead, officer, supervisor
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    department: Mapped["Department"] = relationship("Department", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="department_memberships")
