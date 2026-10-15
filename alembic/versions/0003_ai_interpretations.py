"""AI assist interpretations table migration

Revision ID: 0003_ai_interpretations
Revises: 0002_shared_and_complaints
Create Date: 2026-10-14 23:50:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_ai_interpretations"
down_revision: Union[str, None] = "0002_shared_and_complaints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_interpretations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=False),
        sa.Column(
            "parsed_output",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("recommendation_status", sa.String(32), server_default="PENDING", nullable=False),
        sa.Column(
            "decided_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ai_interpretations_complaint_id", "ai_interpretations", ["complaint_id"])
    op.create_index("ix_ai_interpretations_input_hash", "ai_interpretations", ["input_hash"])
    op.create_index(
        "ix_ai_interpretations_recommendation_status",
        "ai_interpretations",
        ["recommendation_status"],
    )


def downgrade() -> None:
    op.drop_table("ai_interpretations")
