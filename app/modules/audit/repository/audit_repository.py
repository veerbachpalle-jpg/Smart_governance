from collections.abc import Sequence
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import decode_cursor, encode_cursor
from app.modules.audit.models.audit import AuditEvent
from app.modules.audit.schemas.audit import AuditFilterParams


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_latest_event(self) -> Optional[AuditEvent]:
        stmt = select(AuditEvent).order_by(desc(AuditEvent.sequence_number)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def insert_event(self, event: AuditEvent) -> AuditEvent:
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_events(
        self, params: AuditFilterParams
    ) -> tuple[list[AuditEvent], Optional[str], bool, int]:
        stmt = select(AuditEvent)

        if params.entity_type:
            stmt = stmt.where(AuditEvent.entity_type == params.entity_type)
        if params.entity_id:
            stmt = stmt.where(AuditEvent.entity_id == params.entity_id)
        if params.actor_id:
            stmt = stmt.where(AuditEvent.actor_id == params.actor_id)
        if params.action:
            stmt = stmt.where(AuditEvent.action == params.action)
        if params.start_time:
            stmt = stmt.where(AuditEvent.occurred_at >= params.start_time)
        if params.end_time:
            stmt = stmt.where(AuditEvent.occurred_at <= params.end_time)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_res = await self.session.execute(count_stmt)
        total_count = count_res.scalar_one() or 0

        # Keyset pagination on occurred_at and id descending
        if params.cursor:
            cursor_dt, cursor_id = decode_cursor(params.cursor)
            stmt = stmt.where(
                (AuditEvent.occurred_at < cursor_dt)
                | ((AuditEvent.occurred_at == cursor_dt) & (AuditEvent.id < cursor_id))
            )

        stmt = stmt.order_by(desc(AuditEvent.occurred_at), desc(AuditEvent.id))
        stmt = stmt.limit(params.limit + 1)

        res = await self.session.execute(stmt)
        rows = list(res.scalars().all())

        has_more = len(rows) > params.limit
        items = rows[: params.limit]

        next_cursor = None
        if has_more and items:
            last_item = items[-1]
            next_cursor = encode_cursor(last_item.occurred_at, last_item.id)

        return items, next_cursor, has_more, total_count

    async def get_all_ordered(self) -> Sequence[AuditEvent]:
        stmt = select(AuditEvent).order_by(AuditEvent.sequence_number.asc())
        result = await self.session.execute(stmt)
        return result.scalars().all()
