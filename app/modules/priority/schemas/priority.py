import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PriorityPolicyCreate(BaseModel):
    policy_name: str = Field(..., min_length=2, max_length=128)
    language: str = Field(default="all", max_length=16)
    keyword_pattern: str = Field(..., min_length=2, max_length=255)
    elevate_to_priority: str = Field(default="CRITICAL", pattern="^(CRITICAL|HIGH|MEDIUM|LOW)$")
    description: str | None = None
    is_active: bool = True


class PriorityPolicyResponse(BaseModel):
    id: uuid.UUID
    policy_name: str
    language: str
    keyword_pattern: str
    elevate_to_priority: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PriorityAssessmentResponse(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID
    model_priority: str
    model_confidence: float
    model_reasoning: str
    rule_hits: list[dict[str, Any]]
    final_suggested_priority: str
    suggested_sla_hours: int
    is_safety_critical: bool
    recommendation_status: str
    decided_by_id: uuid.UUID | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PriorityQueueItem(BaseModel):
    complaint_id: uuid.UUID
    tracking_number: str
    title: str
    ward_name: str | None
    final_suggested_priority: str
    rule_hits_count: int
    created_at: datetime


class AcceptPriorityRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class OverridePriorityRequest(BaseModel):
    priority: str = Field(..., pattern="^(CRITICAL|HIGH|MEDIUM|LOW)$")
    reason: str = Field(
        ..., min_length=5, max_length=1000, description="Mandatory reason for overriding priority"
    )


class RejectPriorityRequest(BaseModel):
    reason: str = Field(
        ..., min_length=5, max_length=1000, description="Mandatory reason for rejecting priority"
    )
