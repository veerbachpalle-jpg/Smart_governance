import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class AddActivityRequest(BaseModel):
    activity_type: str = Field(default="NOTE_ADDED", max_length=64)
    visibility: str = Field(default="INTERNAL", pattern="^(INTERNAL|CITIZEN_VISIBLE)$")
    message: str = Field(..., min_length=2, max_length=2000)
    metadata: Optional[dict[str, Any]] = None


class CitizenUpdateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=128)
    message: str = Field(..., min_length=2, max_length=2000)


class CaseActivityResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    activity_type: str
    visibility: str
    message: str
    created_at: datetime
    activity_metadata: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class CitizenTimelineItem(BaseModel):
    id: uuid.UUID
    time: datetime
    status: str
    department: Optional[str] = None
    message: str
    activity_type: str

    model_config = ConfigDict(from_attributes=True)
