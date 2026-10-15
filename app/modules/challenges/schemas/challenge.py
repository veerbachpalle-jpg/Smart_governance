import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProposeResolutionRequest(BaseModel):
    remediation_summary: str = Field(
        ..., min_length=5, max_length=2000, description="Mandatory physical remediation summary"
    )
    root_cause_identified: Optional[str] = Field(default=None, max_length=1000)
    attachment_ids: list[uuid.UUID] = Field(
        ..., min_length=1, description="Mandatory photographic/documentary proof of remediation"
    )
    review_window_days: int = Field(default=7, ge=1, le=30)


class ConfirmResolutionRequest(BaseModel):
    feedback: Optional[str] = Field(default=None, max_length=1000)


class CitizenChallengeRequest(BaseModel):
    challenge_type: str = Field(
        default="RESOLUTION", pattern="^(RESOLUTION|REJECTION|OFFICIAL_ACTION|PRIORITY)$"
    )
    reason: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Mandatory justification for contesting official action or resolution",
    )
    attachment_ids: list[uuid.UUID] = Field(default_factory=list)


class ChallengeReviewRequest(BaseModel):
    verdict: str = Field(
        ...,
        pattern="^(UPHELD|OVERTURNED)$",
        description="UPHELD (citizen dispute valid -> reopens case) or OVERTURNED (challenge dismissed -> closes case)",
    )
    rationale: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Mandatory written justification for review decision",
    )
    action_taken: Optional[str] = Field(default=None, max_length=1000)


class ResolutionProposalResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    proposing_officer_id: uuid.UUID
    remediation_summary: str
    root_cause_identified: Optional[str] = None
    officer_verified: bool
    officer_verified_at: Optional[datetime] = None
    review_window_expires_at: datetime
    status: str
    evidence_attachment_ids: list[uuid.UUID] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChallengeReviewResponse(BaseModel):
    id: uuid.UUID
    challenge_id: uuid.UUID
    reviewer_id: uuid.UUID
    verdict: str
    rationale: str
    action_taken: Optional[str] = None
    reviewed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CitizenChallengeResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    resolution_proposal_id: Optional[uuid.UUID] = None
    citizen_id: uuid.UUID
    challenge_type: str
    reason: str
    status: str
    sla_expires_at: datetime
    is_escalated: bool
    escalated_at: Optional[datetime] = None
    review: Optional[ChallengeReviewResponse] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
