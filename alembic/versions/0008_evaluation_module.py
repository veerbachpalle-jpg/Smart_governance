"""Evaluation module migration

Revision ID: 0008_evaluation_module
Revises: 0007_notifications_and_chaos
Create Date: 2026-10-15 03:30:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_evaluation_module"
down_revision: Union[str, None] = "0007_notifications_and_chaos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. eval_datasets
    op.create_table(
        "eval_datasets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("dataset_name", sa.String(100), index=True, nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sample_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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

    # 2. eval_runs
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "dataset_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("eval_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_identifier", sa.String(100), index=True, nullable=False),
        sa.Column(
            "task_type",
            sa.String(50),
            server_default="full_pipeline",
            index=True,
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(50),
            server_default="RUNNING",
            index=True,
            nullable=False,
        ),
        sa.Column(
            "run_by",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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

    # 3. eval_results
    op.create_table(
        "eval_results",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(100), index=True, nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("confusion_matrix", sa.JSON(), nullable=True),
        sa.Column("raw_metrics", sa.JSON(), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
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


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_table("eval_runs")
    op.drop_table("eval_datasets")
