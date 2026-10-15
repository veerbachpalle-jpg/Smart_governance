import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RoutingRuleCreate(BaseModel):
    category: str = Field(..., min_length=2, max_length=128)
    sub_category: str | None = Field(default=None, max_length=128)
    ward_id: uuid.UUID | None = None
    department_id: uuid.UUID
    priority_override: str | None = Field(default=None, max_length=32)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    is_active: bool = True


class RoutingRuleUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=2, max_length=128)
    sub_category: str | None = Field(default=None, max_length=128)
    ward_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    priority_override: str | None = Field(default=None, max_length=32)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    is_active: bool | None = None


class RoutingRuleResponse(BaseModel):
    id: uuid.UUID
    rule_version: int
    category: str
    sub_category: str | None = None
    ward_id: uuid.UUID | None = None
    department_id: uuid.UUID
    priority_override: str | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DepartmentCandidate(BaseModel):
    department_id: uuid.UUID
    department_name: str
    confidence: float
    reasons: list[str]


class RoutingRecommendationResponse(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID
    rule_version_used: int | None = None
    primary_department_id: uuid.UUID
    recommended_departments: list[dict[str, Any]]
    confidence: float
    recommendation_status: str
    decided_by_id: uuid.UUID | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AcceptRoutingRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class OverrideRoutingRequest(BaseModel):
    department_id: uuid.UUID
    reason: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Mandatory justification for overriding routing",
    )


class RejectRoutingRequest(BaseModel):
    reason: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Mandatory justification for rejecting routing",
    )
