import uuid
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_assist.models.ai_interpretation import AIInterpretation


class AIInterpretationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, interpretation: AIInterpretation) -> AIInterpretation:
        self.session.add(interpretation)
        await self.session.flush()
        return interpretation

    async def get_by_id(self, interpretation_id: uuid.UUID) -> Optional[AIInterpretation]:
        stmt = select(AIInterpretation).where(AIInterpretation.id == interpretation_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_by_complaint_id(
        self, complaint_id: uuid.UUID
    ) -> Optional[AIInterpretation]:
        stmt = (
            select(AIInterpretation)
            .where(AIInterpretation.complaint_id == complaint_id)
            .order_by(desc(AIInterpretation.created_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_complaint_id(self, complaint_id: uuid.UUID) -> list[AIInterpretation]:
        stmt = (
            select(AIInterpretation)
            .where(AIInterpretation.complaint_id == complaint_id)
            .order_by(desc(AIInterpretation.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
