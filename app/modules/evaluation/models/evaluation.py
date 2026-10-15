import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDMixin


class EvalDataset(Base, TimestampMixin, UUIDMixin):
    """Represents a versioned benchmark dataset used for system evaluation."""

    __tablename__ = "eval_datasets"

    dataset_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    runs: Mapped[list["EvalRun"]] = relationship(
        "EvalRun",
        back_populates="dataset",
        cascade="all, delete-orphan",
    )


class EvalRun(Base, TimestampMixin, UUIDMixin):
    """Execution run of the evaluation harness against a specific model/provider."""

    __tablename__ = "eval_runs"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("eval_datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_identifier: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    task_type: Mapped[str] = mapped_column(
        String(50), default="full_pipeline", index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="RUNNING", index=True, nullable=False
    )  # RUNNING, COMPLETED, FAILED
    run_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dataset: Mapped["EvalDataset"] = relationship("EvalDataset", back_populates="runs")
    results: Mapped[list["EvalResult"]] = relationship(
        "EvalResult",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EvalResult(Base, TimestampMixin, UUIDMixin):
    """Detailed evaluation metrics and confusion matrices recorded for an evaluation run."""

    __tablename__ = "eval_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    confusion_matrix: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=True,
    )
    raw_metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    run: Mapped["EvalRun"] = relationship("EvalRun", back_populates="results")
