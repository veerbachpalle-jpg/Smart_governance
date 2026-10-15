import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    sequence_number: int
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor_id: uuid.UUID | None = None
    actor_role: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    old_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    occurred_at: datetime
    previous_hash: str
    current_hash: str

    model_config = ConfigDict(from_attributes=True)


class AuditVerifyResponse(BaseModel):
    is_valid: bool
    total_events: int = 0
    message: str = "Audit chain integrity verified."
    broken_at_sequence: int | None = None
    event_id: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None


class AuditFilterParams(BaseModel):
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    action: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
