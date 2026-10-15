"""Cases and activity tables migration

Revision ID: 0005_cases_and_activity
Revises: 0004_routing_priority_duplicates
Create Date: 2026-10-15 01:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_cases_and_activity"
down_revision: Union[str, None] = "0004_routing_priority_duplicates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Cases
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("case_number", sa.String(32), unique=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="TRIAGE_REVIEW", nullable=False),
        sa.Column("priority", sa.String(32), server_default="MEDIUM", nullable=False),
        sa.Column(
            "lead_department_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_officer_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_cases_case_number", "cases", ["case_number"])
    op.create_index("ix_cases_status", "cases", ["status"])
    op.create_index("ix_cases_priority", "cases", ["priority"])

    # 2. Case Complaints
    op.create_table(
        "case_complaints",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_case_complaints_case_id", "case_complaints", ["case_id"])
    op.create_index("ix_case_complaints_complaint_id", "case_complaints", ["complaint_id"])

    # 3. Case Departments with partial unique index for lead department
    op.create_table(
        "case_departments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_lead", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "added_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("case_id", "department_id", name="uq_case_department"),
    )
    op.create_index("ix_case_departments_case_id", "case_departments", ["case_id"])
    op.create_index("ix_case_departments_department_id", "case_departments", ["department_id"])
    op.create_index(
        "uq_case_lead_department",
        "case_departments",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("is_lead IS TRUE"),
        sqlite_where=sa.text("is_lead = 1"),
    )

    # 4. Case Reassign Requests
    op.create_table(
        "case_reassign_requests",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "current_department_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=False,
        ),
        sa.Column(
            "suggested_department_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="PENDING", nullable=False),
        sa.Column(
            "decided_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_case_reassign_requests_case_id", "case_reassign_requests", ["case_id"])
    op.create_index("ix_case_reassign_requests_status", "case_reassign_requests", ["status"])

    # 5. Case Activities
    op.create_table(
        "case_activities",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("activity_type", sa.String(64), nullable=False),
        sa.Column("visibility", sa.String(32), server_default="INTERNAL", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "activity_metadata",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_case_activities_case_id", "case_activities", ["case_id"])
    op.create_index("ix_case_activities_activity_type", "case_activities", ["activity_type"])
    op.create_index("ix_case_activities_visibility", "case_activities", ["visibility"])

    # 6. Citizen Updates
    op.create_table(
        "citizen_updates",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_citizen_updates_case_id", "citizen_updates", ["case_id"])


def downgrade() -> None:
    op.drop_table("citizen_updates")
    op.drop_table("case_activities")
    op.drop_table("case_reassign_requests")
    op.drop_table("case_departments")
    op.drop_table("case_complaints")
    op.drop_table("cases")
