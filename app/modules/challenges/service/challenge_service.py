import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ForbiddenError, NotFoundError
from app.core.outbox import enqueue_outbox_event
from app.modules.activity.models.activity import CaseActivity
from app.modules.audit.service.audit_service import AuditService
from app.modules.cases.models.case import Case, CaseComplaint
from app.modules.cases.repository.case_repository import CaseRepository
from app.modules.cases.schemas.case import CaseResponse
from app.modules.cases.service.case_service import CaseService
from app.modules.cases.service.state_machine import CaseStateMachine
from app.modules.challenges.models.challenge import (
    ChallengeReview,
    CitizenChallenge,
    ReopenEvent,
    ResolutionProposal,
)
from app.modules.challenges.repository.challenge_repository import ChallengeRepository
from app.modules.challenges.schemas.challenge import (
    ChallengeReviewRequest,
    ChallengeReviewResponse,
    CitizenChallengeRequest,
    CitizenChallengeResponse,
    ConfirmResolutionRequest,
    ProposeResolutionRequest,
    ResolutionProposalResponse,
)
from app.modules.complaints.models.complaint import Attachment
from app.modules.complaints.repository.complaint_repository import ComplaintRepository
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole
from app.modules.notifications.service.notification_service import NotificationService

logger = logging.getLogger("app.challenges.service")


class ChallengeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ChallengeRepository(session)
        self.case_repo = CaseRepository(session)
        self.complaint_repo = ComplaintRepository(session)
        self.state_machine = CaseStateMachine(session)
        self.audit_service = AuditService(session)
        self.case_service = CaseService(session)

    def _build_proposal_response(
        self, proposal: ResolutionProposal, attachment_ids: list[uuid.UUID]
    ) -> ResolutionProposalResponse:
        return ResolutionProposalResponse(
            id=proposal.id,
            case_id=proposal.case_id,
            proposing_officer_id=proposal.proposing_officer_id,
            remediation_summary=proposal.remediation_summary,
            root_cause_identified=proposal.root_cause_identified,
            officer_verified=proposal.officer_verified,
            officer_verified_at=proposal.officer_verified_at,
            review_window_expires_at=proposal.review_window_expires_at,
            status=proposal.status,
            evidence_attachment_ids=attachment_ids,
            created_at=proposal.created_at,
        )

    def _build_challenge_response(self, challenge: CitizenChallenge) -> CitizenChallengeResponse:
        review_resp = None
        if challenge.review:
            review_resp = ChallengeReviewResponse(
                id=challenge.review.id,
                challenge_id=challenge.review.challenge_id,
                reviewer_id=challenge.review.reviewer_id,
                verdict=challenge.review.verdict,
                rationale=challenge.review.rationale,
                action_taken=challenge.review.action_taken,
                reviewed_at=challenge.review.reviewed_at,
            )

        return CitizenChallengeResponse(
            id=challenge.id,
            case_id=challenge.case_id,
            resolution_proposal_id=challenge.resolution_proposal_id,
            citizen_id=challenge.citizen_id,
            challenge_type=challenge.challenge_type,
            reason=challenge.reason,
            status=challenge.status,
            sla_expires_at=challenge.sla_expires_at,
            is_escalated=challenge.is_escalated,
            escalated_at=challenge.escalated_at,
            review=review_resp,
            created_at=challenge.created_at,
        )

    async def propose_resolution(
        self,
        current_user: User,
        case_id: uuid.UUID,
        payload: ProposeResolutionRequest,
    ) -> ResolutionProposalResponse:
        """Formal resolution proposal requiring verified proof attachments, summary, and human officer sign-off."""
        case = await self.case_repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        # Must have at least 1 evidence attachment
        if not payload.attachment_ids:
            raise BadRequestError(
                "A resolution proposal requires at least one verified evidence attachment.",
                code="EVIDENCE_REQUIRED",
            )

        # Verify attachments exist in DB
        stmt_att = select(Attachment).where(Attachment.id.in_(payload.attachment_ids))
        res_att = await self.session.execute(stmt_att)
        found_attachments = list(res_att.scalars().all())
        if len(found_attachments) != len(payload.attachment_ids):
            raise BadRequestError(
                "One or more evidence attachment IDs were not found.",
                code="ATTACHMENT_NOT_FOUND",
            )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=payload.review_window_days)

        proposal = ResolutionProposal(
            case_id=case.id,
            proposing_officer_id=current_user.id,
            remediation_summary=payload.remediation_summary.strip(),
            root_cause_identified=payload.root_cause_identified.strip()
            if payload.root_cause_identified
            else None,
            officer_verified=True,
            officer_verified_at=now,
            review_window_expires_at=expires_at,
            status="PROPOSED",
        )
        await self.repo.create_proposal(proposal)

        # Link attachments to proposal
        await self.repo.link_attachments_to_proposal(
            proposal_id=proposal.id,
            case_id=case.id,
            attachment_ids=payload.attachment_ids,
        )

        # Transition state machine: IN_PROGRESS -> RESOLUTION_PROPOSED -> CITIZEN_REVIEW
        if case.status != "RESOLUTION_PROPOSED":
            await self.state_machine.transition(
                case=case,
                target_state="RESOLUTION_PROPOSED",
                actor=current_user,
                reason=payload.remediation_summary.strip(),
            )

        await self.state_machine.transition(
            case=case,
            target_state="CITIZEN_REVIEW",
            actor=current_user,
            reason=f"Citizen review window opened for {payload.review_window_days} days.",
            metadata={"proposal_id": str(proposal.id)},
        )

        return self._build_proposal_response(proposal, payload.attachment_ids)

    async def _resolve_case(self, case_id: uuid.UUID, current_user: User) -> Optional[Case]:
        case = await self.case_repo.get_case_by_id(case_id)
        if case:
            return case
        case = await self.case_repo.get_case_for_complaint(case_id)
        if case:
            return case
        complaint = await self.complaint_repo.get_by_id(case_id)
        if complaint:
            now = datetime.now(timezone.utc)
            case_number = f"CASE-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
            case = Case(
                id=uuid.uuid4(),
                case_number=case_number,
                title=f"Case: {complaint.original_title}",
                description=complaint.original_description,
                status="CITIZEN_REVIEW",
                priority="HIGH",
                created_by_id=current_user.id,
            )
            self.session.add(case)
            await self.session.flush()
            cc = CaseComplaint(case_id=case.id, complaint_id=complaint.id, is_primary=True)
            self.session.add(cc)
            await self.session.flush()
            return case
        return None

    async def confirm_resolution(
        self,
        current_user: User,
        case_id: uuid.UUID,
        payload: ConfirmResolutionRequest,
    ) -> CaseResponse:
        """Citizen explicitly confirms satisfaction with resolution, triggering permanent case closure."""
        case = await self._resolve_case(case_id, current_user)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        proposal = await self.repo.get_latest_proposal(case.id)
        if not proposal or not proposal.officer_verified:
            raise BadRequestError(
                "Cannot close case: No verified resolution proposal found.",
                code="EVIDENCE_REQUIRED",
            )

        attachments = await self.repo.get_proposal_attachments(proposal.id)
        if not attachments:
            raise BadRequestError(
                "Cannot close case: Verified resolution proposal must have at least one evidence attachment.",
                code="EVIDENCE_REQUIRED",
            )

        proposal.status = "ACCEPTED"

        # Transition case to CLOSED
        close_reason = (
            payload.feedback.strip()
            if payload.feedback
            else "Citizen confirmed resolution satisfaction."
        )
        await self.state_machine.transition(
            case=case,
            target_state="CLOSED",
            actor=current_user,
            reason=close_reason,
            metadata={"proposal_id": str(proposal.id)} if proposal else {},
        )

        full_case = await self.case_repo.get_case_by_id(case.id)
        assert full_case is not None
        return self.case_service._build_response(full_case)

    async def file_challenge(
        self,
        current_user: User,
        case_id: uuid.UUID,
        payload: CitizenChallengeRequest,
    ) -> CitizenChallengeResponse:
        """Citizen files a formal dispute against resolution, rejection, action, or priority."""
        case = await self._resolve_case(case_id, current_user)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        proposal = await self.repo.get_latest_proposal(case.id)

        now = datetime.now(timezone.utc)
        # SLA for challenge review: 48 hours
        sla_expires_at = now + timedelta(hours=48)

        challenge = CitizenChallenge(
            case_id=case.id,
            resolution_proposal_id=proposal.id if proposal else None,
            citizen_id=current_user.id,
            challenge_type=payload.challenge_type,
            reason=payload.reason.strip(),
            status="PENDING",
            sla_expires_at=sla_expires_at,
            is_escalated=False,
        )
        await self.repo.create_challenge(challenge)

        if payload.attachment_ids:
            await self.repo.link_attachments_to_challenge(
                challenge_id=challenge.id,
                case_id=case.id,
                attachment_ids=payload.attachment_ids,
            )

        if proposal:
            proposal.status = "CHALLENGED"

        # Transition case state to CHALLENGED
        await self.state_machine.transition(
            case=case,
            target_state="CHALLENGED",
            actor=current_user,
            reason=payload.reason.strip(),
            metadata={
                "challenge_id": str(challenge.id),
                "challenge_type": payload.challenge_type,
            },
        )

        # Dispatch notification to supervisor
        try:
            from app.modules.identity.models.user import User as UserModel
            stmt_sup = select(UserModel).where(
                UserModel.role.in_(["supervisor", "admin"]),
                UserModel.is_active.is_(True),
            )
            res_sup = await self.session.execute(stmt_sup)
            supervisors = list(res_sup.scalars().all())

            notif_service = NotificationService(self.session)
            case_label = case.case_number or str(case.id)[:8]
            notif_title = f"Case {case_label} Reopened by Citizen"
            notif_msg = f"Citizen objected to resolution on '{case.title}'. Reason: {payload.reason.strip()}"

            recipients = {s.email for s in supervisors if s.email}
            if not recipients:
                recipients = {"supervisor@example.com"}

            for recipient in recipients:
                await notif_service.send_notification(
                    recipient=recipient,
                    title=notif_title,
                    message=notif_msg,
                    notification_type="CASE_REOPENED",
                    metadata={
                        "case_id": str(case.id),
                        "challenge_id": str(challenge.id),
                        "reason": payload.reason.strip(),
                    },
                )
            logger.info("Supervisor notification sent to %s for reopened case %s", recipients, case_label)
        except Exception as n_err:
            logger.warning("Failed to dispatch reopen notification to supervisor: %s", n_err)

        fresh_challenge = await self.repo.get_challenge_by_id(challenge.id)
        assert fresh_challenge is not None
        return self._build_challenge_response(fresh_challenge)

    async def review_challenge(
        self,
        reviewer: User,
        challenge_id: uuid.UUID,
        payload: ChallengeReviewRequest,
    ) -> CitizenChallengeResponse:
        """Supervisor independently reviews dispute with strict anti-self-review enforcement."""
        challenge = await self.repo.get_challenge_by_id(challenge_id)
        if not challenge:
            raise NotFoundError(
                f"Challenge '{challenge_id}' not found.", code="CHALLENGE_NOT_FOUND"
            )

        case = await self.case_repo.get_case_by_id(challenge.case_id)
        if not case:
            raise NotFoundError(f"Case '{challenge.case_id}' not found.", code="CASE_NOT_FOUND")

        proposal = (
            await self.repo.get_proposal_by_id(challenge.resolution_proposal_id)
            if challenge.resolution_proposal_id
            else None
        )

        # -----------------------------------------------------------------
        # STRICT ANTI-SELF-REVIEW INVARIANT:
        # Reviewer MUST NOT be the citizen, the assigned officer, the proposing
        # officer, case creator, or any actor in the previous chain of action.
        # -----------------------------------------------------------------
        chain_actor_ids: set[uuid.UUID] = {challenge.citizen_id}
        if case.created_by_id:
            chain_actor_ids.add(case.created_by_id)
        if case.assigned_officer_id:
            chain_actor_ids.add(case.assigned_officer_id)
        if proposal and proposal.proposing_officer_id:
            chain_actor_ids.add(proposal.proposing_officer_id)

        # Check all actors from case activity history
        stmt_acts = select(CaseActivity.actor_id).where(CaseActivity.case_id == case.id)
        res_acts = await self.session.execute(stmt_acts)
        for act_actor_id in res_acts.scalars().all():
            if act_actor_id:
                chain_actor_ids.add(act_actor_id)

        if reviewer.id in chain_actor_ids:
            raise ForbiddenError(
                "Reviewer was part of the original chain of action for this case and is strictly barred from self-reviewing.",
                code="SELF_REVIEW_BLOCKED",
            )

        # Create review entry
        now = datetime.now(timezone.utc)
        review = ChallengeReview(
            challenge_id=challenge.id,
            reviewer_id=reviewer.id,
            verdict=payload.verdict,
            rationale=payload.rationale.strip(),
            action_taken=payload.action_taken.strip() if payload.action_taken else None,
            reviewed_at=now,
        )
        await self.repo.create_review(review)

        # Process verdict side-effects
        if payload.verdict == "OVERTURNED":
            # Dispute is validated; previous official decision/resolution is overturned!
            challenge.status = "OVERTURNED"

            # Create immutable ReopenEvent
            reopen_event = ReopenEvent(
                case_id=case.id,
                trigger_source="CHALLENGE_OVERTURNED",
                challenge_id=challenge.id,
                authorized_by_id=reviewer.id,
                reason=payload.rationale.strip(),
                reopened_at=now,
            )
            await self.repo.create_reopen_event(reopen_event)

            # Move case to REOPENED -> IN_PROGRESS
            await self.state_machine.transition(
                case=case,
                target_state="REOPENED",
                actor=reviewer,
                reason=f"Resolution overturned by supervisor: {payload.rationale.strip()}",
                metadata={"challenge_id": str(challenge.id)},
            )
            await self.state_machine.transition(
                case=case,
                target_state="IN_PROGRESS",
                actor=reviewer,
                reason="Field remediation resumed following overturned challenge decision.",
                metadata={"challenge_id": str(challenge.id)},
            )

        elif payload.verdict == "UPHELD":
            # Original resolution stands; challenge dismissed
            challenge.status = "UPHELD"
            if proposal:
                proposal.status = "ACCEPTED"

            # Finalize case to CLOSED
            await self.state_machine.transition(
                case=case,
                target_state="CLOSED",
                actor=reviewer,
                reason=f"Original resolution upheld by supervisor review: {payload.rationale.strip()}",
                metadata={"challenge_id": str(challenge.id)},
            )

        fresh_challenge = await self.repo.get_challenge_by_id(challenge.id)
        assert fresh_challenge is not None
        return self._build_challenge_response(fresh_challenge)

    async def process_expired_review_windows(
        self, cutoff_time: Optional[datetime] = None
    ) -> list[uuid.UUID]:
        """Worker job: Automatically closes cases whose citizen review window expired with no challenge."""
        now = cutoff_time or datetime.now(timezone.utc)
        expired_proposals = await self.repo.list_expired_proposals(cutoff_time=now)
        closed_case_ids: list[uuid.UUID] = []

        for p in expired_proposals:
            # Check if there is an active challenge on this proposal or case
            active_challenges = [c for c in p.challenges if c.status in {"PENDING", "UNDER_REVIEW"}]
            if active_challenges:
                continue

            # Verify attachments exist
            attachments = await self.repo.get_proposal_attachments(p.id)
            if not attachments:
                continue

            case = await self.case_repo.get_case_by_id(p.case_id)
            if not case or case.status != "CITIZEN_REVIEW":
                continue

            p.status = "AUTO_CLOSED"

            # Transition case to CLOSED
            proposing_officer = p.proposing_officer or User(
                id=p.proposing_officer_id,
                role=UserRole.OFFICER.value,
                email="system@municipality.gov",
                full_name="System Automated Worker",
            )
            await self.state_machine.transition(
                case=case,
                target_state="CLOSED",
                actor=proposing_officer,
                reason="Citizen review window expired with no challenge filed; auto-closed.",
                metadata={"proposal_id": str(p.id)},
            )
            closed_case_ids.append(case.id)

        return closed_case_ids

    async def process_challenge_sla_breaches(
        self, cutoff_time: Optional[datetime] = None
    ) -> list[uuid.UUID]:
        """Worker job: Automatically escalates challenges that breached SLA timer."""
        now = cutoff_time or datetime.now(timezone.utc)
        breached_challenges = await self.repo.list_breached_challenges(cutoff_time=now)
        escalated_ids: list[uuid.UUID] = []

        for c in breached_challenges:
            c.is_escalated = True
            c.escalated_at = now

            # Audit event
            await self.audit_service.record_event(
                entity_type="challenge",
                entity_id=c.id,
                action="challenge.sla_escalated",
                actor_id=c.citizen_id,
                actor_role=UserRole.CITIZEN.value,
                old_state={"is_escalated": False},
                new_state={"is_escalated": True, "escalated_at": now.isoformat()},
            )

            # Case activity
            activity = CaseActivity(
                case_id=c.case_id,
                actor_id=c.citizen_id,
                activity_type="CHALLENGE_ESCALATED",
                visibility="INTERNAL",
                message=f"Challenge '{c.id}' breached review SLA and was escalated to supervisor queue.",
                activity_metadata={"challenge_id": str(c.id)},
            )
            self.session.add(activity)

            # Transactional outbox
            await enqueue_outbox_event(
                session=self.session,
                event_type="challenge.escalated",
                aggregate_type="challenge",
                aggregate_id=c.id,
                payload={
                    "challenge_id": str(c.id),
                    "case_id": str(c.case_id),
                    "escalated_at": now.isoformat(),
                },
            )
            escalated_ids.append(c.id)

        await self.session.flush()
        return escalated_ids

    async def get_latest_proposal(
        self, current_user: User, case_id: uuid.UUID
    ) -> ResolutionProposalResponse:
        case = await self.case_repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        proposal = await self.repo.get_latest_proposal(case.id)
        if not proposal:
            raise NotFoundError(
                f"No resolution proposal found for case '{case_id}'.",
                code="PROPOSAL_NOT_FOUND",
            )
        attachments = await self.repo.get_proposal_attachments(proposal.id)
        return self._build_proposal_response(proposal, [a.id for a in attachments])

    async def get_challenge_status(
        self, current_user: User, case_id: uuid.UUID
    ) -> CitizenChallengeResponse:
        challenge = await self.repo.get_latest_challenge_for_case(case_id)
        if not challenge:
            raise NotFoundError(
                f"No challenge found for case '{case_id}'.", code="CHALLENGE_NOT_FOUND"
            )
        return self._build_challenge_response(challenge)

    async def get_challenge_by_id(
        self, current_user: User, challenge_id: uuid.UUID
    ) -> CitizenChallengeResponse:
        challenge = await self.repo.get_challenge_by_id(challenge_id)
        if not challenge:
            raise NotFoundError(
                f"Challenge '{challenge_id}' not found.", code="CHALLENGE_NOT_FOUND"
            )
        return self._build_challenge_response(challenge)

    async def list_challenges(
        self, current_user: User, status: Optional[str] = None
    ) -> list[CitizenChallengeResponse]:
        challenges = await self.repo.list_challenges(status=status)
        return [self._build_challenge_response(c) for c in challenges]
