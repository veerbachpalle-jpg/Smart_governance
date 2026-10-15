import uuid
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.priority.models.priority import PriorityAssessment, PriorityPolicy


class PriorityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_policy(self, policy: PriorityPolicy) -> PriorityPolicy:
        self.session.add(policy)
        await self.session.flush()
        return policy

    async def list_policies(self, is_active: bool | None = None) -> list[PriorityPolicy]:
        stmt = select(PriorityPolicy)
        if is_active is not None:
            stmt = stmt.where(PriorityPolicy.is_active == is_active)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_assessment(self, assessment: PriorityAssessment) -> PriorityAssessment:
        self.session.add(assessment)
        await self.session.flush()
        return assessment

    async def get_latest_assessment(self, complaint_id: uuid.UUID) -> Optional[PriorityAssessment]:
        stmt = (
            select(PriorityAssessment)
            .where(PriorityAssessment.complaint_id == complaint_id)
            .order_by(desc(PriorityAssessment.created_at))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_critical_queue(self) -> list[PriorityAssessment]:
        stmt = (
            select(PriorityAssessment)
            .where(
                PriorityAssessment.is_safety_critical == True,  # noqa: E712
                PriorityAssessment.recommendation_status == "PENDING",
            )
            .order_by(desc(PriorityAssessment.created_at))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
