"""Regional upvote counter and priority queue support.

Revision ID: 0009_regional_upvotes_priority
Revises: 0008_evaluation_module
Create Date: 2026-10-29 15:00:00.000000
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0009_regional_upvotes_priority"
down_revision: Union[str, None] = "0008_evaluation_module"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "complaints",
        sa.Column("upvote_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index("ix_complaints_upvote_count", "complaints", ["upvote_count"])
    op.execute(
        sa.text(
            """
            UPDATE complaints
            SET upvote_count = (
                SELECT COUNT(*)
                FROM complaint_supports
                WHERE complaint_supports.complaint_id = complaints.id
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_complaints_upvote_count", table_name="complaints")
    op.drop_column("complaints", "upvote_count")
