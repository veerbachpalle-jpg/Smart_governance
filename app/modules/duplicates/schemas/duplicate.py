import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DuplicateCandidateResponse(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID
    candidate_complaint_id: uuid.UUID
    candidate_tracking_number: str
    candidate_title: str
    candidate_status: str
    overall_score: float
    geo_similarity: float
    semantic_similarity: float
    category_similarity: float
    time_similarity: float
    distance_meters: float
    status: str
    decided_by_id: uuid.UUID | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LinkDuplicateRequest(BaseModel):
    reason: str | None = Field(
        default=None, max_length=500, description="Optional notes for linking duplicate incident"
    )


class DismissDuplicateRequest(BaseModel):
    reason: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Mandatory reason for dismissing duplicate candidate",
    )


class NearbySimilarReport(BaseModel):
    id: uuid.UUID
    tracking_number: str
    title: str
    latitude: float
    longitude: float
    created_at: datetime
    status: str
    distance_meters: float
    support_count: int


class SupportComplaintResponse(BaseModel):
    complaint_id: uuid.UUID
    support_count: int
    message: str
