import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LanguageDetectResult(BaseModel):
    """Result of language detection and optional English translation."""

    language_code: str = Field(default="en", max_length=16)
    language_name: str = Field(default="English", max_length=64)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    requires_translation: bool = Field(default=False)
    translated_title: str
    translated_description: str

    model_config = ConfigDict(from_attributes=True)


class InterpretationResult(BaseModel):
    """Structured AI triage interpretation enforcing strict separation between facts and hypotheses."""

    category: str = Field(..., min_length=2, max_length=128)
    sub_category: str = Field(..., min_length=2, max_length=128)
    location_hints: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    reported_facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    potential_root_causes: list[str] = Field(default_factory=list)
    officer_summary: str = Field(..., min_length=5)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("reported_facts")
    @classmethod
    def validate_reported_facts(cls, facts: list[str]) -> list[str]:
        """Ensures reported_facts contains only direct observational statements and never asserts root causes."""
        forbidden_cause_patterns = [
            r"\broot cause is\b",
            r"\bdefinitely caused by\b",
            r"\bproven cause\b",
            r"\bthe reason why\b",
            r"\bthe culprit is\b",
        ]
        for fact in facts:
            for pat in forbidden_cause_patterns:
                if re.search(pat, fact, re.IGNORECASE):
                    raise ValueError(
                        f"Reported fact contains root cause assertion: '{fact}'. "
                        "Root causes must be placed in potential_root_causes as unverified hypotheses."
                    )
        return facts

    @field_validator("potential_root_causes")
    @classmethod
    def validate_potential_root_causes(cls, causes: list[str]) -> list[str]:
        """Ensures every potential root cause is explicitly framed as an unverified hypothesis."""
        sanitized: list[str] = []
        hypothesis_markers = [
            "hypothesis",
            "possible",
            "potential",
            "suspected",
            "unverified",
            "inferred",
            "likely",
        ]
        for cause in causes:
            c_lower = cause.lower()
            if not any(marker in c_lower for marker in hypothesis_markers):
                sanitized.append(f"Unverified hypothesis: {cause}")
            else:
                sanitized.append(cause)
        return sanitized

    model_config = ConfigDict(from_attributes=True)


class DepartmentRouteResult(BaseModel):
    """Department routing recommendation."""

    recommended_department: str
    secondary_departments: list[str] = Field(default_factory=list)
    justification: str
    confidence: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(from_attributes=True)


class PriorityAssessmentResult(BaseModel):
    """Priority and urgency scoring result."""

    recommended_priority: str
    suggested_sla_hours: int = Field(ge=1, le=720)
    hazard_indicators: dict[str, bool] = Field(default_factory=dict)
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(from_attributes=True)


class AcceptInterpretationRequest(BaseModel):
    """Officer accepts the AI recommendation."""

    notes: str | None = Field(default=None, max_length=500)


class OverrideInterpretationRequest(BaseModel):
    """Officer overrides the AI recommendation with custom category/details."""

    reason: str = Field(
        ..., min_length=5, max_length=1000, description="Mandatory justification for overriding AI"
    )
    category: str | None = Field(default=None, max_length=128)
    sub_category: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=500)


class RejectInterpretationRequest(BaseModel):
    """Officer rejects the AI recommendation entirely."""

    reason: str = Field(
        ..., min_length=5, max_length=1000, description="Mandatory justification for rejection"
    )


class AIInterpretationResponse(BaseModel):
    """Public schema representing a stored AI recommendation record."""

    id: uuid.UUID
    complaint_id: uuid.UUID
    model: str
    prompt_version: str
    input_hash: str
    raw_output: str
    parsed_output: dict[str, Any]
    confidence: float
    latency_ms: int
    recommendation_status: str
    decided_by_id: uuid.UUID | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
