"""Add uq_case_single_lead index and evidence_urls to case_reassign_requests.

Revision ID: 0010_phone_auth_and_lead_constraint
Revises: 0009_regional_upvotes_priority
Create Date: 2026-10-30 00:00:00.000000
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0010_phone_auth_and_lead_constraint"
down_revision: Union[str, None] = "0009_regional_upvotes_priority"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add evidence_urls JSON column to case_reassign_requests
    op.add_column(
        "case_reassign_requests",
        sa.Column("evidence_urls", sa.JSON(), nullable=True),
    )

    # 2. Add uq_case_single_lead partial unique index (matching specification)
    # Using safe creation for both PostgreSQL and SQLite
    op.create_index(
        "uq_case_single_lead",
        "case_departments",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("is_lead IS TRUE"),
        sqlite_where=sa.text("is_lead = 1"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("uq_case_single_lead", table_name="case_departments")
    op.drop_column("case_reassign_requests", "evidence_urls")
