import uuid
from collections.abc import Sequence
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import decode_cursor, encode_cursor
from app.modules.complaints.models.complaint import Attachment, Complaint, Ward
from app.modules.complaints.schemas.complaint import ComplaintFilterParams


class WardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> Sequence[Ward]:
        stmt = select(Ward).order_by(Ward.ward_number.asc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id(self, ward_id: uuid.UUID) -> Optional[Ward]:
        stmt = select(Ward).where(Ward.id == ward_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, ward: Ward) -> Ward:
        self.session.add(ward)
        await self.session.flush()
        return ward


class AttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, attachment: Attachment) -> Attachment:
        self.session.add(attachment)
        await self.session.flush()
        return attachment

    async def get_by_id(self, attachment_id: uuid.UUID) -> Optional[Attachment]:
        stmt = select(Attachment).where(Attachment.id == attachment_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_ids(self, attachment_ids: list[uuid.UUID]) -> Sequence[Attachment]:
        if not attachment_ids:
            return []
        stmt = select(Attachment).where(Attachment.id.in_(attachment_ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_complaint(self, complaint_id: uuid.UUID) -> Sequence[Attachment]:
        stmt = (
            select(Attachment)
            .where(Attachment.complaint_id == complaint_id)
            .order_by(Attachment.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ComplaintRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, complaint: Complaint) -> Complaint:
        self.session.add(complaint)
        await self.session.flush()
        return complaint

    async def get_by_id(self, complaint_id: uuid.UUID) -> Optional[Complaint]:
        stmt = (
            select(Complaint)
            .options(selectinload(Complaint.attachments))
            .where(Complaint.id == complaint_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_tracking_number(self, tracking_number: str) -> Optional[Complaint]:
        stmt = (
            select(Complaint)
            .options(selectinload(Complaint.attachments))
            .where(Complaint.tracking_number == tracking_number.strip().upper())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_complaints(
        self,
        citizen_id: Optional[uuid.UUID],
        params: ComplaintFilterParams,
    ) -> tuple[list[Complaint], Optional[str], bool, int]:
        stmt = select(Complaint).options(selectinload(Complaint.attachments))

        if citizen_id is not None:
            stmt = stmt.where(Complaint.citizen_id == citizen_id)

        if params.status:
            stmt = stmt.where(Complaint.status == params.status.strip().upper())
        if params.ward_name:
            stmt = stmt.where(Complaint.ward_name == params.ward_name.strip())
        if params.start_time:
            stmt = stmt.where(Complaint.created_at >= params.start_time)
        if params.end_time:
            stmt = stmt.where(Complaint.created_at <= params.end_time)

        # Count total matches
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_res = await self.session.execute(count_stmt)
        total_count = count_res.scalar_one() or 0

        # Keyset pagination on (created_at desc, id desc)
        if params.cursor:
            cursor_dt, cursor_id = decode_cursor(params.cursor)
            stmt = stmt.where(
                (Complaint.created_at < cursor_dt)
                | ((Complaint.created_at == cursor_dt) & (Complaint.id < cursor_id))
            )

        stmt = stmt.order_by(desc(Complaint.created_at), desc(Complaint.id))
        stmt = stmt.limit(params.limit + 1)

        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())

        has_more = len(rows) > params.limit
        items = rows[: params.limit]

        next_cursor = None
        if has_more and items:
            last_item = items[-1]
            next_cursor = encode_cursor(last_item.created_at, last_item.id)

        return items, next_cursor, has_more, total_count
