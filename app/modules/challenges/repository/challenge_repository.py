import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.challenges.models.challenge import (
    ChallengeReview,
    CitizenChallenge,
    ReopenEvent,
    ResolutionProposal,
)
from app.modules.complaints.models.complaint import Attachment


class ChallengeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_proposal(self, proposal: ResolutionProposal) -> ResolutionProposal:
        self.session.add(proposal)
        await self.session.flush()
        return proposal

    async def get_proposal_by_id(self, proposal_id: uuid.UUID) -> Optional[ResolutionProposal]:
        stmt = (
            select(ResolutionProposal)
            .options(
                selectinload(ResolutionProposal.case),
                selectinload(ResolutionProposal.challenges),
            )
            .where(ResolutionProposal.id == proposal_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_latest_proposal(self, case_id: uuid.UUID) -> Optional[ResolutionProposal]:
        stmt = (
            select(ResolutionProposal)
            .options(
                selectinload(ResolutionProposal.case),
                selectinload(ResolutionProposal.challenges),
            )
            .where(ResolutionProposal.case_id == case_id)
            .order_by(desc(ResolutionProposal.created_at))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_expired_proposals(self, cutoff_time: datetime) -> list[ResolutionProposal]:
        stmt = (
            select(ResolutionProposal)
            .options(
                selectinload(ResolutionProposal.case),
                selectinload(ResolutionProposal.challenges),
            )
            .where(
                ResolutionProposal.status == "PROPOSED",
                ResolutionProposal.review_window_expires_at <= cutoff_time,
            )
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def link_attachments_to_proposal(
        self, proposal_id: uuid.UUID, case_id: uuid.UUID, attachment_ids: list[uuid.UUID]
    ) -> None:
        if not attachment_ids:
            return
        stmt = (
            update(Attachment)
            .where(Attachment.id.in_(attachment_ids))
            .values(resolution_proposal_id=proposal_id, case_id=case_id)
        )
        await self.session.execute(stmt)

    async def get_proposal_attachments(self, proposal_id: uuid.UUID) -> list[Attachment]:
        stmt = select(Attachment).where(Attachment.resolution_proposal_id == proposal_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_challenge(self, challenge: CitizenChallenge) -> CitizenChallenge:
        self.session.add(challenge)
        await self.session.flush()
        return challenge

    async def get_challenge_by_id(self, challenge_id: uuid.UUID) -> Optional[CitizenChallenge]:
        stmt = (
            select(CitizenChallenge)
            .options(
                selectinload(CitizenChallenge.case),
                selectinload(CitizenChallenge.resolution_proposal),
                selectinload(CitizenChallenge.review).selectinload(ChallengeReview.reviewer),
            )
            .where(CitizenChallenge.id == challenge_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_latest_challenge_for_case(self, case_id: uuid.UUID) -> Optional[CitizenChallenge]:
        stmt = (
            select(CitizenChallenge)
            .options(
                selectinload(CitizenChallenge.case),
                selectinload(CitizenChallenge.resolution_proposal),
                selectinload(CitizenChallenge.review).selectinload(ChallengeReview.reviewer),
            )
            .where(CitizenChallenge.case_id == case_id)
            .order_by(desc(CitizenChallenge.created_at))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_challenges(self, status: Optional[str] = None) -> list[CitizenChallenge]:
        stmt = (
            select(CitizenChallenge)
            .options(
                selectinload(CitizenChallenge.case),
                selectinload(CitizenChallenge.resolution_proposal),
                selectinload(CitizenChallenge.review).selectinload(ChallengeReview.reviewer),
            )
            .order_by(desc(CitizenChallenge.created_at))
        )
        if status:
            stmt = stmt.where(CitizenChallenge.status == status)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def list_breached_challenges(self, cutoff_time: datetime) -> list[CitizenChallenge]:
        stmt = (
            select(CitizenChallenge)
            .options(selectinload(CitizenChallenge.case))
            .where(
                CitizenChallenge.status.in_(["PENDING", "UNDER_REVIEW"]),
                CitizenChallenge.sla_expires_at <= cutoff_time,
                CitizenChallenge.is_escalated == False,  # noqa: E712
            )
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def link_attachments_to_challenge(
        self, challenge_id: uuid.UUID, case_id: uuid.UUID, attachment_ids: list[uuid.UUID]
    ) -> None:
        if not attachment_ids:
            return
        stmt = (
            update(Attachment)
            .where(Attachment.id.in_(attachment_ids))
            .values(challenge_id=challenge_id, case_id=case_id)
        )
        await self.session.execute(stmt)

    async def create_review(self, review: ChallengeReview) -> ChallengeReview:
        self.session.add(review)
        await self.session.flush()
        return review

    async def create_reopen_event(self, event: ReopenEvent) -> ReopenEvent:
        self.session.add(event)
        await self.session.flush()
        return event
