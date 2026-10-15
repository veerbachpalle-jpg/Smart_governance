import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.routing.models.routing import RoutingRecommendation, RoutingRule


class RoutingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_rule(self, rule: RoutingRule) -> RoutingRule:
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def get_rule_by_id(self, rule_id: uuid.UUID) -> Optional[RoutingRule]:
        stmt = (
            select(RoutingRule)
            .options(selectinload(RoutingRule.department))
            .where(RoutingRule.id == rule_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_rules(
        self,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> list[RoutingRule]:
        stmt = select(RoutingRule).options(selectinload(RoutingRule.department))
        if category:
            stmt = stmt.where(RoutingRule.category == category)
        if is_active is not None:
            stmt = stmt.where(RoutingRule.is_active == is_active)
        stmt = stmt.order_by(desc(RoutingRule.rule_version), desc(RoutingRule.created_at))
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def find_matching_active_rules(
        self,
        category: str,
        sub_category: str | None = None,
        ward_id: uuid.UUID | None = None,
        at_time: datetime | None = None,
    ) -> list[RoutingRule]:
        if at_time is None:
            at_time = datetime.now(timezone.utc)

        stmt = (
            select(RoutingRule)
            .options(selectinload(RoutingRule.department))
            .where(
                RoutingRule.is_active == True,  # noqa: E712
                RoutingRule.category == category,
                RoutingRule.effective_from <= at_time,
                or_(RoutingRule.effective_to.is_(None), RoutingRule.effective_to >= at_time),
            )
        )
        if ward_id is not None:
            stmt = stmt.where(or_(RoutingRule.ward_id.is_(None), RoutingRule.ward_id == ward_id))

        stmt = stmt.order_by(desc(RoutingRule.rule_version))
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_max_rule_version(self) -> int:
        stmt = select(RoutingRule.rule_version).order_by(desc(RoutingRule.rule_version)).limit(1)
        res = await self.session.execute(stmt)
        val = res.scalar_one_or_none()
        return val or 0

    async def create_recommendation(self, rec: RoutingRecommendation) -> RoutingRecommendation:
        self.session.add(rec)
        await self.session.flush()
        return rec

    async def get_latest_recommendation(
        self, complaint_id: uuid.UUID
    ) -> Optional[RoutingRecommendation]:
        stmt = (
            select(RoutingRecommendation)
            .where(RoutingRecommendation.complaint_id == complaint_id)
            .order_by(desc(RoutingRecommendation.created_at))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()
