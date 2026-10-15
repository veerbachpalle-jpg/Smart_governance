import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.evaluation.models.evaluation import EvalDataset, EvalResult, EvalRun


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_dataset(self, dataset: EvalDataset) -> EvalDataset:
        self.session.add(dataset)
        await self.session.flush()
        await self.session.refresh(dataset)
        return dataset

    async def get_dataset_by_name_and_version(self, name: str, version: str) -> EvalDataset | None:
        stmt = select(EvalDataset).where(
            EvalDataset.dataset_name == name,
            EvalDataset.version == version,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_dataset(self, dataset_id: uuid.UUID) -> EvalDataset | None:
        stmt = select(EvalDataset).where(EvalDataset.id == dataset_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_run(self, run: EvalRun) -> EvalRun:
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def get_run(self, run_id: uuid.UUID) -> EvalRun | None:
        stmt = (
            select(EvalRun)
            .where(EvalRun.id == run_id)
            .options(selectinload(EvalRun.dataset), selectinload(EvalRun.results))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_runs(self, limit: int = 50, offset: int = 0) -> Sequence[EvalRun]:
        stmt = (
            select(EvalRun)
            .order_by(EvalRun.started_at.desc())
            .options(selectinload(EvalRun.dataset), selectinload(EvalRun.results))
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def create_result(self, result: EvalResult) -> EvalResult:
        self.session.add(result)
        await self.session.flush()
        await self.session.refresh(result)
        return result

    async def update_run(
        self,
        run_id: uuid.UUID,
        status: str,
        completed_at: datetime | None = None,
    ) -> EvalRun | None:
        run = await self.get_run(run_id)
        if run:
            run.status = status
            if completed_at:
                run.completed_at = completed_at
            await self.session.flush()
        return run
