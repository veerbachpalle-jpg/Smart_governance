import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ManualTriageRequest(BaseModel):
    category: str = Field(
        ..., min_length=2, max_length=128, description="Municipal grievance category"
    )
    sub_category: Optional[str] = Field(default=None, max_length=128)
    department_id: uuid.UUID = Field(..., description="Target department to route complaint")
    priority: str = Field(
        ..., pattern="^(CRITICAL|HIGH|MEDIUM|LOW)$", description="Assessed priority band"
    )
    notes: Optional[str] = Field(
        default=None, max_length=2000, description="Officer triage and routing rationale"
    )


class ManualTriageQueueItemResponse(BaseModel):
    id: uuid.UUID
    tracking_number: str
    original_title: str
    original_description: str
    status: str
    original_language: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ManualTriageResultResponse(BaseModel):
    complaint_id: uuid.UUID
    case_id: Optional[uuid.UUID] = None
    status: str
    category: str
    sub_category: Optional[str] = None
    department_id: uuid.UUID
    priority: str
    source: str = "MANUAL"
    ai_interpretation_id: uuid.UUID
    routing_recommendation_id: uuid.UUID
    priority_assessment_id: uuid.UUID
    decided_by_id: uuid.UUID
    decided_at: datetime

    model_config = ConfigDict(from_attributes=True)
