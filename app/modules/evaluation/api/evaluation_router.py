import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.db.session import get_db
from app.modules.evaluation.repository.evaluation_repository import EvaluationRepository
from app.modules.evaluation.schemas.evaluation import (
    CalibrationBucket,
    DuplicateMetrics,
    EvalResultDetail,
    EvalRunDetail,
    EvalRunSummary,
    FalseNegativeItem,
    LatencyPercentiles,
)
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

router = APIRouter(prefix="/eval", tags=["Evaluation Harness"])


@router.get(
    "/runs",
    response_model=list[EvalRunSummary],
    summary="List all evaluation benchmark runs (Admin/Auditor only)",
)
async def list_eval_runs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AUDITOR)),
) -> list[EvalRunSummary]:
    repo = EvaluationRepository(session)
    runs = await repo.list_runs(limit=limit, offset=offset)

    summaries = []
    for r in runs:
        primary_metrics: dict[str, float] = {}
        for res in r.results:
            primary_metrics[res.metric_name] = res.metric_value

        summaries.append(
            EvalRunSummary(
                id=r.id,
                dataset_id=r.dataset_id,
                dataset_name=r.dataset.dataset_name if r.dataset else None,
                model_identifier=r.model_identifier,
                task_type=r.task_type,
                status=r.status,
                started_at=r.started_at,
                completed_at=r.completed_at,
                primary_metrics=primary_metrics,
            )
        )
    return summaries


@router.get(
    "/runs/{id}",
    response_model=EvalRunDetail,
    summary="Get detailed evaluation run metrics including confusion matrices and false negatives (Admin/Auditor only)",
)
async def get_eval_run_detail(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AUDITOR)),
) -> EvalRunDetail:
    repo = EvaluationRepository(session)
    run = await repo.get_run(id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation run '{id}' not found.",
        )

    results_detail = [EvalResultDetail.model_validate(res) for res in run.results]

    confusion_matrices: dict[str, Any] = {}
    false_negatives: list[FalseNegativeItem] = []
    calibration_buckets: list[CalibrationBucket] = []
    latency_percentiles: LatencyPercentiles | None = None
    duplicate_metrics: DuplicateMetrics | None = None
    abstention_rate = 0.0

    for res in run.results:
        if res.confusion_matrix:
            confusion_matrices[res.metric_name] = res.confusion_matrix

        if res.metric_name == "safety_critical_recall" and res.raw_metrics:
            raw_fns = res.raw_metrics.get("false_negatives", [])
            for fn in raw_fns:
                false_negatives.append(FalseNegativeItem(**fn))

        if res.metric_name == "overall_evaluation" and res.raw_metrics:
            raw_cal = res.raw_metrics.get("calibration_buckets", [])
            for cb in raw_cal:
                calibration_buckets.append(CalibrationBucket(**cb))
            raw_lat = res.raw_metrics.get("latency_percentiles")
            if raw_lat:
                latency_percentiles = LatencyPercentiles(**raw_lat)

        if res.metric_name == "duplicate_metrics" and res.raw_metrics:
            duplicate_metrics = DuplicateMetrics(**res.raw_metrics)

        if res.metric_name == "abstention_rate":
            abstention_rate = res.metric_value

    return EvalRunDetail(
        id=run.id,
        dataset_id=run.dataset_id,
        dataset_name=run.dataset.dataset_name if run.dataset else None,
        dataset_version=run.dataset.version if run.dataset else None,
        model_identifier=run.model_identifier,
        task_type=run.task_type,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        results=results_detail,
        false_negatives=false_negatives,
        confusion_matrices=confusion_matrices,
        calibration_buckets=calibration_buckets,
        latency_percentiles=latency_percentiles,
        duplicate_metrics=duplicate_metrics,
        abstention_rate=abstention_rate,
    )
