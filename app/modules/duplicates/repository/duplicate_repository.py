import uuid
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.complaints.models.complaint import Complaint
from app.modules.duplicates.models.duplicate import (
    ComplaintEmbedding,
    ComplaintSupport,
    DuplicateCandidate,
)


class DuplicateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_embedding(self, embedding: ComplaintEmbedding) -> ComplaintEmbedding:
        # Check if already exists
        existing = await self.get_embedding(embedding.complaint_id)
        if existing:
            existing.embedding = embedding.embedding
            existing.model_name = embedding.model_name
            await self.session.flush()
            return existing
        self.session.add(embedding)
        await self.session.flush()
        return embedding

    async def get_embedding(self, complaint_id: uuid.UUID) -> Optional[ComplaintEmbedding]:
        stmt = select(ComplaintEmbedding).where(ComplaintEmbedding.complaint_id == complaint_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def save_candidate(self, candidate: DuplicateCandidate) -> DuplicateCandidate:
        self.session.add(candidate)
        await self.session.flush()
        return candidate

    async def get_candidate_by_id(self, candidate_id: uuid.UUID) -> Optional[DuplicateCandidate]:
        stmt = (
            select(DuplicateCandidate)
            .options(
                selectinload(DuplicateCandidate.complaint),
                selectinload(DuplicateCandidate.candidate_complaint),
            )
            .where(DuplicateCandidate.id == candidate_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_candidates(self, complaint_id: uuid.UUID) -> list[DuplicateCandidate]:
        stmt = (
            select(DuplicateCandidate)
            .options(
                selectinload(DuplicateCandidate.complaint),
                selectinload(DuplicateCandidate.candidate_complaint),
            )
            .where(DuplicateCandidate.complaint_id == complaint_id)
            .order_by(desc(DuplicateCandidate.overall_score))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def add_support(self, support: ComplaintSupport) -> ComplaintSupport:
        self.session.add(support)
        await self.session.flush()
        return support

    async def get_support_count(self, complaint_id: uuid.UUID) -> int:
        stmt = select(func.count(ComplaintSupport.id)).where(
            ComplaintSupport.complaint_id == complaint_id
        )
        res = await self.session.execute(stmt)
        return res.scalar_one() or 0

    async def has_citizen_supported(self, complaint_id: uuid.UUID, citizen_id: uuid.UUID) -> bool:
        stmt = select(func.count(ComplaintSupport.id)).where(
            ComplaintSupport.complaint_id == complaint_id,
            ComplaintSupport.citizen_id == citizen_id,
        )
        res = await self.session.execute(stmt)
        count = res.scalar_one() or 0
        return count > 0

    async def list_other_recent_complaints(
        self, exclude_complaint_id: uuid.UUID | None = None
    ) -> list[Complaint]:
        stmt = select(Complaint).where(Complaint.status != "REJECTED_WITH_REASON")
        if exclude_complaint_id:
            stmt = stmt.where(Complaint.id != exclude_complaint_id)
        stmt = stmt.order_by(desc(Complaint.created_at))
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
