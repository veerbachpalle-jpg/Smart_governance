import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FalseNegativeItem(BaseModel):
    sample_id: str
    title: str
    description: str
    language: str
    expected_priority: str
    predicted_priority: str
    rule_hits: list[str] = Field(default_factory=list)
    failure_reason: str = "Model/policy failed to escalate safety-critical grievance"


class CalibrationBucket(BaseModel):
    bucket_range: str
    sample_count: int
    mean_confidence: float
    accuracy: float
    calibration_error: float


class LatencyPercentiles(BaseModel):
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    avg_ms: float


class DuplicateMetrics(BaseModel):
    precision_at_k: float
    recall_at_k: float
    k: int = 3
    evaluated_duplicate_samples: int


class EvalResultDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    metric_name: str
    metric_value: float
    confusion_matrix: dict[str, Any] | None = None
    raw_metrics: dict[str, Any] | None = None
    evaluated_at: datetime


class EvalRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    model_identifier: str
    task_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    primary_metrics: dict[str, float] = Field(default_factory=dict)


class EvalRunDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    dataset_version: str | None = None
    model_identifier: str
    task_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    results: list[EvalResultDetail] = Field(default_factory=list)
    false_negatives: list[FalseNegativeItem] = Field(default_factory=list)
    confusion_matrices: dict[str, Any] = Field(default_factory=dict)
    calibration_buckets: list[CalibrationBucket] = Field(default_factory=list)
    latency_percentiles: LatencyPercentiles | None = None
    duplicate_metrics: DuplicateMetrics | None = None
    abstention_rate: float = 0.0
