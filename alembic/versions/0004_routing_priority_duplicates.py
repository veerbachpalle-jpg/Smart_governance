"""Routing, priority, and duplicates tables migration

Revision ID: 0004_routing_priority_duplicates
Revises: 0003_ai_interpretations
Create Date: 2026-10-15 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_routing_priority_duplicates"
down_revision: Union[str, None] = "0003_ai_interpretations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Routing Rules
    op.create_table(
        "routing_rules",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("sub_category", sa.String(128), nullable=True),
        sa.Column(
            "ward_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("wards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "department_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("priority_override", sa.String(32), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
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
    op.create_index("ix_routing_rules_rule_version", "routing_rules", ["rule_version"])
    op.create_index("ix_routing_rules_category", "routing_rules", ["category"])
    op.create_index("ix_routing_rules_is_active", "routing_rules", ["is_active"])

    # 2. Routing Recommendations
    op.create_table(
        "routing_recommendations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_version_used", sa.Integer(), nullable=True),
        sa.Column(
            "primary_department_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recommended_departments",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
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
    op.create_index(
        "ix_routing_recommendations_complaint_id", "routing_recommendations", ["complaint_id"]
    )
    op.create_index(
        "ix_routing_recommendations_recommendation_status",
        "routing_recommendations",
        ["recommendation_status"],
    )

    # 3. Priority Policies
    op.create_table(
        "priority_policies",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("policy_name", sa.String(128), unique=True, nullable=False),
        sa.Column("language", sa.String(16), server_default="all", nullable=False),
        sa.Column("keyword_pattern", sa.String(255), nullable=False),
        sa.Column("elevate_to_priority", sa.String(32), server_default="CRITICAL", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_priority_policies_language", "priority_policies", ["language"])
    op.create_index("ix_priority_policies_is_active", "priority_policies", ["is_active"])

    # 4. Priority Assessments
    op.create_table(
        "priority_assessments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_priority", sa.String(32), nullable=False),
        sa.Column("model_confidence", sa.Float(), nullable=False),
        sa.Column("model_reasoning", sa.Text(), nullable=False),
        sa.Column(
            "rule_hits", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=False
        ),
        sa.Column("final_suggested_priority", sa.String(32), nullable=False),
        sa.Column("suggested_sla_hours", sa.Integer(), nullable=False),
        sa.Column(
            "is_safety_critical", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
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
    op.create_index(
        "ix_priority_assessments_complaint_id", "priority_assessments", ["complaint_id"]
    )
    op.create_index(
        "ix_priority_assessments_final_suggested_priority",
        "priority_assessments",
        ["final_suggested_priority"],
    )
    op.create_index(
        "ix_priority_assessments_is_safety_critical", "priority_assessments", ["is_safety_critical"]
    )
    op.create_index(
        "ix_priority_assessments_recommendation_status",
        "priority_assessments",
        ["recommendation_status"],
    )

    # 5. Complaint Embeddings
    op.create_table(
        "complaint_embeddings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column(
            "embedding", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_complaint_embeddings_complaint_id", "complaint_embeddings", ["complaint_id"]
    )

    # 6. Duplicate Candidates
    op.create_table(
        "duplicate_candidates",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("geo_similarity", sa.Float(), nullable=False),
        sa.Column("semantic_similarity", sa.Float(), nullable=False),
        sa.Column("category_similarity", sa.Float(), nullable=False),
        sa.Column("time_similarity", sa.Float(), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=False),
        sa.Column("status", sa.String(32), server_default="PENDING", nullable=False),
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
    op.create_index(
        "ix_duplicate_candidates_complaint_id", "duplicate_candidates", ["complaint_id"]
    )
    op.create_index(
        "ix_duplicate_candidates_candidate_complaint_id",
        "duplicate_candidates",
        ["candidate_complaint_id"],
    )
    op.create_index("ix_duplicate_candidates_status", "duplicate_candidates", ["status"])

    # 7. Complaint Supports
    op.create_table(
        "complaint_supports",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "citizen_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("complaint_id", "citizen_id", name="uq_complaint_citizen_support"),
    )
    op.create_index("ix_complaint_supports_complaint_id", "complaint_supports", ["complaint_id"])
    op.create_index("ix_complaint_supports_citizen_id", "complaint_supports", ["citizen_id"])


def downgrade() -> None:
    op.drop_table("complaint_supports")
    op.drop_table("duplicate_candidates")
    op.drop_table("complaint_embeddings")
    op.drop_table("priority_assessments")
    op.drop_table("priority_policies")
    op.drop_table("routing_recommendations")
    op.drop_table("routing_rules")
