"""Shared infrastructure and complaints module migration

Revision ID: 0002_shared_and_complaints
Revises: 0001_initial_identity
Create Date: 2026-10-14 15:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_shared_and_complaints"
down_revision: Union[str, None] = "0001_initial_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Outbox Events
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "payload", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=False
        ),
        sa.Column("status", sa.String(32), server_default="PENDING", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="5", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_events_status_created", "outbox_events", ["status", "created_at"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])

    # 2. Dead Letter Events
    op.create_table(
        "dead_letter_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "outbox_event_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("outbox_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "payload", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=False
        ),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column(
            "failed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 3. Append-Only Audit Events
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "sequence_number", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(32), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column(
            "old_state", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True
        ),
        sa.Column(
            "new_state", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("previous_hash", sa.String(64), nullable=False),
        sa.Column("current_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_events_sequence", "audit_events", ["sequence_number"], unique=True)
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])

    # 4. Idempotency Keys
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_path", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_body", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_idempotency_keys_key", "idempotency_keys", ["key"], unique=True)

    # 5. Wards Table
    op.create_table(
        "wards",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("ward_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "boundary_geojson",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column("min_lat", sa.Float(), nullable=False),
        sa.Column("max_lat", sa.Float(), nullable=False),
        sa.Column("min_lon", sa.Float(), nullable=False),
        sa.Column("max_lon", sa.Float(), nullable=False),
    )
    op.create_index("ix_wards_ward_number", "wards", ["ward_number"], unique=True)
    op.create_index("ix_wards_name", "wards", ["name"], unique=True)

    # 6. Complaints Table
    op.create_table(
        "complaints",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tracking_number", sa.String(32), nullable=False),
        sa.Column(
            "citizen_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_title", sa.String(255), nullable=False),
        sa.Column("original_description", sa.Text(), nullable=False),
        sa.Column("original_language", sa.String(16), server_default="en", nullable=False),
        sa.Column("translated_title", sa.String(255), nullable=True),
        sa.Column("translated_description", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column(
            "ward_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("wards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ward_name", sa.String(128), nullable=True),
        sa.Column("channel", sa.String(32), server_default="WEB", nullable=False),
        sa.Column("status", sa.String(32), server_default="SUBMITTED", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_complaints_tracking_number", "complaints", ["tracking_number"], unique=True)
    op.create_index("ix_complaints_citizen_id", "complaints", ["citizen_id"])
    op.create_index("ix_complaints_status", "complaints", ["status"])
    op.create_index("ix_complaints_created_at", "complaints", ["created_at"])
    op.create_index("ix_complaints_ward_name", "complaints", ["ward_name"])

    # 7. Attachments Table
    op.create_table(
        "attachments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "complaint_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "uploader_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_url", sa.String(512), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column(
            "attachment_type", sa.String(32), server_default="CITIZEN_SUBMISSION", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_attachments_complaint_id", "attachments", ["complaint_id"])
    op.create_index("ix_attachments_uploader_id", "attachments", ["uploader_id"])


def downgrade() -> None:
    op.drop_table("attachments")
    op.drop_table("complaints")
    op.drop_table("wards")
    op.drop_table("idempotency_keys")
    op.drop_table("audit_events")
    op.drop_table("dead_letter_events")
    op.drop_table("outbox_events")
