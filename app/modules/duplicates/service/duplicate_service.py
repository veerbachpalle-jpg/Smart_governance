import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, NotFoundError
from app.modules.ai_assist.service.providers import get_embedding_provider
from app.modules.audit.service.audit_service import AuditService
from app.modules.complaints.models.complaint import Complaint
from app.modules.complaints.repository.complaint_repository import ComplaintRepository
from app.modules.duplicates.models.duplicate import (
    ComplaintEmbedding,
    ComplaintSupport,
    DuplicateCandidate,
)
from app.modules.duplicates.repository.duplicate_repository import DuplicateRepository
from app.modules.duplicates.schemas.duplicate import (
    DismissDuplicateRequest,
    DuplicateCandidateResponse,
    LinkDuplicateRequest,
    NearbySimilarReport,
    SupportComplaintResponse,
)
from app.modules.identity.models.user import User

logger = logging.getLogger("app.duplicates.service")


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two GPS coordinates in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Computes cosine similarity between two vector lists."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    sim = dot_product / (norm_a * norm_b)
    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, (sim + 1.0) / 2.0 if sim < 0 else sim))


class DuplicateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DuplicateRepository(session)
        self.complaint_repo = ComplaintRepository(session)
        self.audit_service = AuditService(session)
        self.embedding_provider = get_embedding_provider()

    async def get_or_create_embedding(self, complaint: Complaint) -> ComplaintEmbedding:
        """Retrieves cached embedding or generates and stores vector embedding for complaint."""
        existing = await self.repo.get_embedding(complaint.id)
        if existing:
            return existing

        text_to_embed = f"{complaint.original_title}. {complaint.original_description}"
        if complaint.translated_title:
            text_to_embed += f". {complaint.translated_title}. {complaint.translated_description}"

        vec = await self.embedding_provider.embed_text(text_to_embed)
        emb = ComplaintEmbedding(
            complaint_id=complaint.id,
            model_name="mock-embed-v1"
            if not hasattr(self.embedding_provider, "embedding_model")
            else self.embedding_provider.embedding_model,
            embedding=vec,
        )
        return await self.repo.save_embedding(emb)

    async def search_and_rank_candidates(
        self,
        complaint_id: uuid.UUID,
        radius_meters: float = 3000.0,
        time_window_days: int = 30,
    ) -> list[DuplicateCandidateResponse]:
        """Candidate search combining spatial radius + embedding similarity + category + time window."""
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            raise NotFoundError(
                f"Complaint '{complaint_id}' not found.", code="COMPLAINT_NOT_FOUND"
            )

        # 1. Ensure target complaint has embedding
        complaint_emb = await self.get_or_create_embedding(complaint)

        # 2. Fetch active candidates within time window
        other_complaints = await self.repo.list_other_recent_complaints(
            exclude_complaint_id=complaint.id
        )
        existing_candidates = {
            c.candidate_complaint_id: c for c in await self.repo.list_candidates(complaint.id)
        }

        results: list[DuplicateCandidate] = []

        for other in other_complaints:
            # Time filter
            other_created = other.created_at
            if other_created.tzinfo is None:
                other_created = other_created.replace(tzinfo=timezone.utc)
            complaint_created = complaint.created_at
            if complaint_created.tzinfo is None:
                complaint_created = complaint_created.replace(tzinfo=timezone.utc)

            time_diff_days = abs((complaint_created - other_created).total_seconds()) / 86400.0
            if time_diff_days > time_window_days:
                continue

            # Geo filter
            dist = haversine_distance_meters(
                complaint.latitude, complaint.longitude, other.latitude, other.longitude
            )
            if dist > radius_meters:
                continue

            geo_sim = max(0.0, 1.0 - (dist / radius_meters))
            time_sim = max(0.0, 1.0 - (time_diff_days / float(time_window_days)))

            # Semantic similarity via embedding
            other_emb = await self.get_or_create_embedding(other)
            sem_sim = cosine_similarity(complaint_emb.embedding, other_emb.embedding)

            # Category similarity (keyword heuristic)
            c1_words = set(complaint.original_title.lower().split())
            c2_words = set(other.original_title.lower().split())
            cat_overlap = len(c1_words.intersection(c2_words))
            cat_sim = 1.0 if cat_overlap >= 2 else (0.5 if cat_overlap == 1 else 0.0)

            # Weighted overall score
            overall = 0.35 * geo_sim + 0.35 * sem_sim + 0.15 * cat_sim + 0.15 * time_sim

            if other.id in existing_candidates:
                cand = existing_candidates[other.id]
                cand.overall_score = round(overall, 4)
                cand.geo_similarity = round(geo_sim, 4)
                cand.semantic_similarity = round(sem_sim, 4)
                cand.category_similarity = round(cat_sim, 4)
                cand.time_similarity = round(time_sim, 4)
                cand.distance_meters = round(dist, 1)
            else:
                cand = DuplicateCandidate(
                    complaint_id=complaint.id,
                    candidate_complaint_id=other.id,
                    overall_score=round(overall, 4),
                    geo_similarity=round(geo_sim, 4),
                    semantic_similarity=round(sem_sim, 4),
                    category_similarity=round(cat_sim, 4),
                    time_similarity=round(time_sim, 4),
                    distance_meters=round(dist, 1),
                    status="PENDING",
                )
                cand = await self.repo.save_candidate(cand)
            results.append(cand)

        await self.session.flush()

        # Sort by overall score descending
        results.sort(key=lambda x: x.overall_score, reverse=True)

        responses: list[DuplicateCandidateResponse] = []
        for r in results:
            cand_comp = r.candidate_complaint or await self.complaint_repo.get_by_id(
                r.candidate_complaint_id
            )
            responses.append(
                DuplicateCandidateResponse(
                    id=r.id,
                    complaint_id=r.complaint_id,
                    candidate_complaint_id=r.candidate_complaint_id,
                    candidate_tracking_number=cand_comp.tracking_number if cand_comp else "UNKNOWN",
                    candidate_title=cand_comp.original_title if cand_comp else "",
                    candidate_status=cand_comp.status if cand_comp else "",
                    overall_score=r.overall_score,
                    geo_similarity=r.geo_similarity,
                    semantic_similarity=r.semantic_similarity,
                    category_similarity=r.category_similarity,
                    time_similarity=r.time_similarity,
                    distance_meters=r.distance_meters,
                    status=r.status,
                    decided_by_id=r.decided_by_id,
                    decision_reason=r.decision_reason,
                    decided_at=r.decided_at,
                    created_at=r.created_at,
                )
            )
        return responses

    async def list_candidates(self, complaint_id: uuid.UUID) -> list[DuplicateCandidateResponse]:
        """Lists duplicate candidates for complaint, running search if none generated yet."""
        existing = await self.repo.list_candidates(complaint_id)
        if not existing:
            return await self.search_and_rank_candidates(complaint_id)

        responses: list[DuplicateCandidateResponse] = []
        for r in existing:
            cand_comp = r.candidate_complaint or await self.complaint_repo.get_by_id(
                r.candidate_complaint_id
            )
            responses.append(
                DuplicateCandidateResponse(
                    id=r.id,
                    complaint_id=r.complaint_id,
                    candidate_complaint_id=r.candidate_complaint_id,
                    candidate_tracking_number=cand_comp.tracking_number if cand_comp else "UNKNOWN",
                    candidate_title=cand_comp.original_title if cand_comp else "",
                    candidate_status=cand_comp.status if cand_comp else "",
                    overall_score=r.overall_score,
                    geo_similarity=r.geo_similarity,
                    semantic_similarity=r.semantic_similarity,
                    category_similarity=r.category_similarity,
                    time_similarity=r.time_similarity,
                    distance_meters=r.distance_meters,
                    status=r.status,
                    decided_by_id=r.decided_by_id,
                    decision_reason=r.decision_reason,
                    decided_at=r.decided_at,
                    created_at=r.created_at,
                )
            )
        return responses

    async def link_duplicate(
        self,
        candidate_id: uuid.UUID,
        officer: User,
        payload: LinkDuplicateRequest,
    ) -> DuplicateCandidateResponse:
        """Human officer explicitly links duplicate incident. NEVER AUTO-MERGE (both entities remain intact)."""
        candidate = await self.repo.get_candidate_by_id(candidate_id)
        if not candidate:
            raise NotFoundError(
                f"Duplicate candidate '{candidate_id}' not found.", code="CANDIDATE_NOT_FOUND"
            )

        now = datetime.now(timezone.utc)
        candidate.status = "LINKED"
        candidate.decided_by_id = officer.id
        candidate.decided_at = now
        candidate.decision_reason = payload.reason

        await self.session.flush()

        await self.audit_service.record_event(
            entity_type="duplicate_candidate",
            entity_id=candidate.id,
            action="duplicate.linked",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(candidate.complaint_id),
                "candidate_complaint_id": str(candidate.candidate_complaint_id),
                "status": "LINKED",
                "reason": payload.reason,
            },
        )

        cand_comp = candidate.candidate_complaint or await self.complaint_repo.get_by_id(
            candidate.candidate_complaint_id
        )
        return DuplicateCandidateResponse(
            id=candidate.id,
            complaint_id=candidate.complaint_id,
            candidate_complaint_id=candidate.candidate_complaint_id,
            candidate_tracking_number=cand_comp.tracking_number if cand_comp else "UNKNOWN",
            candidate_title=cand_comp.original_title if cand_comp else "",
            candidate_status=cand_comp.status if cand_comp else "",
            overall_score=candidate.overall_score,
            geo_similarity=candidate.geo_similarity,
            semantic_similarity=candidate.semantic_similarity,
            category_similarity=candidate.category_similarity,
            time_similarity=candidate.time_similarity,
            distance_meters=candidate.distance_meters,
            status=candidate.status,
            decided_by_id=candidate.decided_by_id,
            decision_reason=candidate.decision_reason,
            decided_at=candidate.decided_at,
            created_at=candidate.created_at,
        )

    async def dismiss_duplicate(
        self,
        candidate_id: uuid.UUID,
        officer: User,
        payload: DismissDuplicateRequest,
    ) -> DuplicateCandidateResponse:
        """Human officer explicitly dismisses duplicate candidate with mandatory justification."""
        if not payload.reason or len(payload.reason.strip()) < 5:
            raise BadRequestError(
                "A substantive reason of at least 5 characters is required to dismiss duplicate candidate.",
                code="DISMISS_REASON_REQUIRED",
            )

        candidate = await self.repo.get_candidate_by_id(candidate_id)
        if not candidate:
            raise NotFoundError(
                f"Duplicate candidate '{candidate_id}' not found.", code="CANDIDATE_NOT_FOUND"
            )

        now = datetime.now(timezone.utc)
        candidate.status = "DISMISSED"
        candidate.decided_by_id = officer.id
        candidate.decided_at = now
        candidate.decision_reason = payload.reason.strip()

        await self.session.flush()

        await self.audit_service.record_event(
            entity_type="duplicate_candidate",
            entity_id=candidate.id,
            action="duplicate.dismissed",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(candidate.complaint_id),
                "candidate_complaint_id": str(candidate.candidate_complaint_id),
                "status": "DISMISSED",
                "reason": payload.reason.strip(),
            },
        )

        cand_comp = candidate.candidate_complaint or await self.complaint_repo.get_by_id(
            candidate.candidate_complaint_id
        )
        return DuplicateCandidateResponse(
            id=candidate.id,
            complaint_id=candidate.complaint_id,
            candidate_complaint_id=candidate.candidate_complaint_id,
            candidate_tracking_number=cand_comp.tracking_number if cand_comp else "UNKNOWN",
            candidate_title=cand_comp.original_title if cand_comp else "",
            candidate_status=cand_comp.status if cand_comp else "",
            overall_score=candidate.overall_score,
            geo_similarity=candidate.geo_similarity,
            semantic_similarity=candidate.semantic_similarity,
            category_similarity=candidate.category_similarity,
            time_similarity=candidate.time_similarity,
            distance_meters=candidate.distance_meters,
            status=candidate.status,
            decided_by_id=candidate.decided_by_id,
            decision_reason=candidate.decision_reason,
            decided_at=candidate.decided_at,
            created_at=candidate.created_at,
        )

    async def get_nearby_similar_for_citizens(
        self,
        latitude: float,
        longitude: float,
        radius_meters: float = 2000.0,
    ) -> list[NearbySimilarReport]:
        """Public/Citizen-safe endpoint returning nearby similar reports with strictly NO personal information."""
        complaints = await self.repo.list_other_recent_complaints()
        nearby: list[NearbySimilarReport] = []

        for c in complaints:
            dist = haversine_distance_meters(latitude, longitude, c.latitude, c.longitude)
            if dist <= radius_meters:
                support_count = await self.repo.get_support_count(c.id)
                nearby.append(
                    NearbySimilarReport(
                        id=c.id,
                        tracking_number=c.tracking_number,
                        title=c.original_title,
                        latitude=c.latitude,
                        longitude=c.longitude,
                        created_at=c.created_at,
                        status=c.status,
                        distance_meters=round(dist, 1),
                        support_count=support_count,
                    )
                )

        nearby.sort(key=lambda x: x.distance_meters)
        return nearby[:20]

    async def support_complaint(
        self,
        complaint_id: uuid.UUID,
        citizen: User,
    ) -> SupportComplaintResponse:
        """Citizen clicks 'This is the same issue' to endorse existing complaint."""
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            raise NotFoundError(
                f"Complaint '{complaint_id}' not found.", code="COMPLAINT_NOT_FOUND"
            )

        has_supported = await self.repo.has_citizen_supported(complaint_id, citizen.id)
        if has_supported:
            count = await self.repo.get_support_count(complaint_id)
            return SupportComplaintResponse(
                complaint_id=complaint.id,
                support_count=count,
                message="You have already registered support for this complaint.",
            )

        support = ComplaintSupport(
            complaint_id=complaint.id,
            citizen_id=citizen.id,
        )
        await self.repo.add_support(support)
        count = await self.repo.get_support_count(complaint_id)

        await self.audit_service.record_event(
            entity_type="complaint",
            entity_id=complaint.id,
            action="complaint.supported",
            actor_id=citizen.id,
            actor_role=citizen.role,
            new_state={"support_count": count},
        )

        return SupportComplaintResponse(
            complaint_id=complaint.id,
            support_count=count,
            message="Support successfully added to grievance report.",
        )
