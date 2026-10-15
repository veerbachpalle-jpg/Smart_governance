import uuid
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.activity.models.activity import CaseActivity, CitizenUpdate


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_activity(self, activity: CaseActivity) -> CaseActivity:
        self.session.add(activity)
        await self.session.flush()
        return activity

    async def list_activities(
        self,
        case_id: uuid.UUID,
        visibility: Optional[str] = None,
    ) -> list[CaseActivity]:
        stmt = (
            select(CaseActivity)
            .options(selectinload(CaseActivity.actor), selectinload(CaseActivity.case))
            .where(CaseActivity.case_id == case_id)
        )
        if visibility:
            stmt = stmt.where(CaseActivity.visibility == visibility)
        stmt = stmt.order_by(desc(CaseActivity.created_at))
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_citizen_update(self, citizen_update: CitizenUpdate) -> CitizenUpdate:
        self.session.add(citizen_update)
        await self.session.flush()
        return citizen_update

    async def list_citizen_timeline(self, case_id: uuid.UUID) -> list[CaseActivity]:
        """Returns ONLY CITIZEN_VISIBLE activities for timeline display."""
        stmt = (
            select(CaseActivity)
            .options(selectinload(CaseActivity.case))
            .where(
                CaseActivity.case_id == case_id,
                CaseActivity.visibility == "CITIZEN_VISIBLE",
            )
            .order_by(desc(CaseActivity.created_at))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
