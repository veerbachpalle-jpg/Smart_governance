import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AttachmentResponse(BaseModel):
    id: uuid.UUID
    file_url: str
    file_name: str
    mime_type: str
    file_size_bytes: int
    sha256_hash: str
    attachment_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreateComplaintRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10)
    original_language: str = Field(default="en", max_length=16)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    address: str = Field(min_length=3, max_length=500)
    channel: str = Field(default="WEB", max_length=32)
    attachment_ids: list[uuid.UUID] = Field(default_factory=list)


class ComplaintResponse(BaseModel):
    id: uuid.UUID
    tracking_number: str
    citizen_id: uuid.UUID
    original_title: str
    original_description: str
    original_language: str
    translated_title: str | None = None
    translated_description: str | None = None
    latitude: float
    longitude: float
    address: str
    ward_id: uuid.UUID | None = None
    ward_name: str | None = None
    channel: str
    status: str
    upvote_count: int = 0
    priority_band: str = "MEDIUM"
    sla_urgency_points: int = 0
    composite_score: int = 0
    sla_deadline: datetime | None = None
    sla_seconds_remaining: int | None = None
    is_sla_overdue: bool = False
    department_id: uuid.UUID | None = None
    department_name: str | None = None
    ward_number: int | None = None
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PublicTrackingResponse(BaseModel):
    """Publicly safe tracking response containing no private citizen information."""

    tracking_number: str
    status: str
    ward_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ComplaintFilterParams(BaseModel):
    status: str | None = None
    ward_id: uuid.UUID | None = None
    ward_number: int | None = None
    ward_name: str | None = None
    department_id: uuid.UUID | None = None
    department_name: str | None = None
    sort: Literal["priority_score", "upvotes", "recent"] = "priority_score"
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None


class TrendingComplaintResponse(BaseModel):
    id: uuid.UUID
    tracking_number: str
    title: str
    latitude: float
    longitude: float
    ward_id: uuid.UUID | None = None
    ward_name: str | None = None
    ward_number: int | None = None
    status: str
    created_at: datetime
    distance_meters: float
    upvote_count: int
    priority_band: str
    composite_score: int
    upvoted_by_current_user: bool = False
