"""Resolutions and citizen challenges migration

Revision ID: 0006_resolutions_and_challenges
Revises: 0005_cases_and_activity
Create Date: 2026-10-15 02:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_resolutions_and_challenges"
down_revision: Union[str, None] = "0005_cases_and_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Resolution Proposals
    op.create_table(
        "resolution_proposals",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "proposing_officer_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("remediation_summary", sa.Text(), nullable=False),
        sa.Column("root_cause_identified", sa.Text(), nullable=True),
        sa.Column(
            "officer_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("officer_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_window_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), server_default="PROPOSED", index=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 2. Citizen Challenges
    op.create_table(
        "citizen_challenges",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "resolution_proposal_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("resolution_proposals.id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        ),
        sa.Column(
            "citizen_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "challenge_type", sa.String(32), server_default="RESOLUTION", index=True, nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="PENDING", index=True, nullable=False),
        sa.Column("sla_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_escalated",
            sa.Boolean(),
            server_default=sa.text("false"),
            index=True,
            nullable=False,
        ),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 3. Challenge Reviews
    op.create_table(
        "challenge_reviews",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "challenge_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("citizen_challenges.id", ondelete="CASCADE"),
            unique=True,
            index=True,
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("verdict", sa.String(32), index=True, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("action_taken", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 4. Reopen Events
    op.create_table(
        "reopen_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("trigger_source", sa.String(64), nullable=False),
        sa.Column(
            "challenge_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("citizen_challenges.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "authorized_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "reopened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 5. Add columns to attachments if not present
    with op.batch_alter_table("attachments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "case_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey("cases.id", ondelete="CASCADE", name="fk_attachments_case_id"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "resolution_proposal_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey(
                    "resolution_proposals.id",
                    ondelete="CASCADE",
                    name="fk_attachments_res_proposal_id",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "challenge_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey(
                    "citizen_challenges.id", ondelete="CASCADE", name="fk_attachments_challenge_id"
                ),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("attachments") as batch_op:
        batch_op.drop_column("challenge_id")
        batch_op.drop_column("resolution_proposal_id")
        batch_op.drop_column("case_id")

    op.drop_table("reopen_events")
    op.drop_table("challenge_reviews")
    op.drop_table("citizen_challenges")
    op.drop_table("resolution_proposals")
