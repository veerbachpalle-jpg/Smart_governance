import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, NotFoundError
from app.modules.audit.service.audit_service import AuditService
from app.modules.complaints.repository.complaint_repository import ComplaintRepository
from app.modules.identity.models.user import Department, User
from app.modules.routing.models.routing import RoutingRecommendation, RoutingRule
from app.modules.routing.repository.routing_repository import RoutingRepository
from app.modules.routing.schemas.routing import (
    AcceptRoutingRequest,
    OverrideRoutingRequest,
    RejectRoutingRequest,
    RoutingRecommendationResponse,
    RoutingRuleCreate,
    RoutingRuleResponse,
    RoutingRuleUpdate,
)

logger = logging.getLogger("app.routing.service")


class RoutingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = RoutingRepository(session)
        self.complaint_repo = ComplaintRepository(session)
        self.audit_service = AuditService(session)

    async def create_rule(
        self, current_user: User, payload: RoutingRuleCreate
    ) -> RoutingRuleResponse:
        """Admin creates a new versioned routing rule."""
        max_ver = await self.repo.get_max_rule_version()
        new_version = max_ver + 1

        effective_from = payload.effective_from or datetime.now(timezone.utc)
        rule = RoutingRule(
            rule_version=new_version,
            category=payload.category.strip(),
            sub_category=payload.sub_category.strip() if payload.sub_category else None,
            ward_id=payload.ward_id,
            department_id=payload.department_id,
            priority_override=payload.priority_override,
            effective_from=effective_from,
            effective_to=payload.effective_to,
            is_active=payload.is_active,
            created_by_id=current_user.id,
        )
        created = await self.repo.create_rule(rule)

        await self.audit_service.record_event(
            entity_type="routing_rule",
            entity_id=created.id,
            action="routing_rule.created",
            actor_id=current_user.id,
            actor_role=current_user.role,
            new_state={
                "rule_version": new_version,
                "category": created.category,
                "department_id": str(created.department_id),
                "is_active": created.is_active,
            },
        )
        return RoutingRuleResponse.model_validate(created)

    async def update_rule(
        self, current_user: User, rule_id: uuid.UUID, payload: RoutingRuleUpdate
    ) -> RoutingRuleResponse:
        """Admin updates an existing routing rule."""
        rule = await self.repo.get_rule_by_id(rule_id)
        if not rule:
            raise NotFoundError(f"Routing rule '{rule_id}' not found.", code="RULE_NOT_FOUND")

        old_state = {"is_active": rule.is_active, "category": rule.category}

        if payload.category is not None:
            rule.category = payload.category.strip()
        if payload.sub_category is not None:
            rule.sub_category = payload.sub_category.strip()
        if payload.ward_id is not None:
            rule.ward_id = payload.ward_id
        if payload.department_id is not None:
            rule.department_id = payload.department_id
        if payload.priority_override is not None:
            rule.priority_override = payload.priority_override
        if payload.effective_from is not None:
            rule.effective_from = payload.effective_from
        if payload.effective_to is not None:
            rule.effective_to = payload.effective_to
        if payload.is_active is not None:
            rule.is_active = payload.is_active

        await self.session.flush()

        await self.audit_service.record_event(
            entity_type="routing_rule",
            entity_id=rule.id,
            action="routing_rule.updated",
            actor_id=current_user.id,
            actor_role=current_user.role,
            old_state=old_state,
            new_state={"is_active": rule.is_active, "category": rule.category},
        )
        return RoutingRuleResponse.model_validate(rule)

    async def list_rules(
        self, category: str | None = None, is_active: bool | None = None
    ) -> list[RoutingRuleResponse]:
        rules = await self.repo.list_rules(category=category, is_active=is_active)
        return [RoutingRuleResponse.model_validate(r) for r in rules]

    async def generate_routing_recommendation(
        self,
        complaint_id: uuid.UUID,
        ml_dept_scores: list[dict[str, Any]] | None = None,
    ) -> RoutingRecommendationResponse:
        """Generates ranked top-3 department routing recommendations using zero-shot ML scores, active rules, and heuristics."""
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            raise NotFoundError(
                f"Complaint '{complaint_id}' not found.", code="COMPLAINT_NOT_FOUND"
            )

        # 1. Fetch all departments
        dept_stmt = select(Department).where(Department.is_active == True)  # noqa: E712
        dept_res = await self.session.execute(dept_stmt)
        all_depts = list(dept_res.scalars().all())

        if not all_depts:
            raise NotFoundError(
                "No municipal departments configured.", code="DEPARTMENTS_NOT_FOUND"
            )

        # 2. Check active routing rules matching complaint
        # Infer category from complaint title/description keywords (including translated text)
        text_corpus = f"{complaint.original_title} {complaint.original_description}"
        if complaint.translated_title:
            text_corpus += f" {complaint.translated_title} {complaint.translated_description}"
        text_corpus = text_corpus.lower()

        inferred_category = "Roads & Footpaths"
        if any(
            k in text_corpus
            for k in [
                "water",
                "leak",
                "pipe",
                "pipeline",
                "tap",
                "meter",
                "drinking",
                "पानी",
                "पाइप",
                "नल",
                "ನೀರು",
                "ನಲ್ಲಿ",
            ]
        ):
            inferred_category = "Water Supply & Sewerage"
        elif any(
            k in text_corpus
            for k in [
                "light",
                "dark",
                "pole",
                "wire",
                "lamp",
                "electric",
                "transformer",
                "बिजली",
                "खंभा",
                "तार",
                "ದೀಪ",
                "ಕಂಬ",
                "ವಿದ್ಯುತ್",
            ]
        ):
            inferred_category = "Electricity & Lighting"
        elif any(
            k in text_corpus
            for k in [
                "garbage",
                "trash",
                "waste",
                "dump",
                "debris",
                "कचरा",
                "कूड़ा",
                "मलबा",
                "ಕಸ",
                "ತ್ಯಾಜ್ಯ",
            ]
        ):
            inferred_category = "Solid Waste Management"
        elif any(
            k in text_corpus
            for k in [
                "drain",
                "gutter",
                "flood",
                "waterlogging",
                "sewage",
                "manhole",
                "नाली",
                "सीवर",
                "मैनहोल",
                "ಚರಂಡಿ",
            ]
        ):
            inferred_category = "Stormwater & Drainage"
        elif any(
            k in text_corpus
            for k in [
                "park",
                "tree",
                "grass",
                "branch",
                "bench",
                "swing",
                "पार्क",
                "पेड़",
                "घास",
                "झूला",
                "ಉದ್ಯಾನ",
                "ಮರ",
            ]
        ):
            inferred_category = "Parks & Recreation"

        now = datetime.now(timezone.utc)
        matching_rules = await self.repo.find_matching_active_rules(
            category=inferred_category,
            ward_id=complaint.ward_id,
            at_time=now,
        )

        ranked: list[dict[str, Any]] = []
        rule_version_used: int | None = None
        primary_dept: Department

        # 2a. Check if zero-shot ML scores were passed or stored in AIInterpretation
        if ml_dept_scores is None:
            try:
                from app.modules.ai_assist.repository.ai_repository import AIInterpretationRepository

                ai_repo = AIInterpretationRepository(self.session)
                interp = await ai_repo.get_latest_by_complaint_id(complaint.id)
                if interp and interp.parsed_output and isinstance(interp.parsed_output, dict):
                    ml_dept_scores = interp.parsed_output.get("dept_scores")
            except Exception:
                ml_dept_scores = None

        if ml_dept_scores and isinstance(ml_dept_scores, list) and len(ml_dept_scores) > 0:
            dept_map: dict[str, Department] = {}
            for d in all_depts:
                code_lower = d.code.lower()
                name_lower = d.name.lower()
                for key, mapped_code in [
                    ("roads", "road"),
                    ("water", "water"),
                    ("electricity", "elec"),
                    ("sanitation", "san"),
                    ("drainage", "drain"),
                    ("parks", "park"),
                ]:
                    if mapped_code in code_lower or mapped_code in name_lower:
                        dept_map[key] = d

            sorted_scores = sorted(
                ml_dept_scores,
                key=lambda x: float(x.get("confidence", 0.0) if isinstance(x, dict) else getattr(x, "confidence", 0.0)),
                reverse=True,
            )
            top_ranked = []
            for item in sorted_scores:
                d_name = item.get("department") if isinstance(item, dict) else getattr(item, "department", "")
                d_conf = float(item.get("confidence", 0.0) if isinstance(item, dict) else getattr(item, "confidence", 0.0))
                matched_dept = dept_map.get(str(d_name).lower())
                if matched_dept and matched_dept not in [r[0] for r in top_ranked]:
                    top_ranked.append((matched_dept, d_conf, d_name))

            if top_ranked:
                primary_dept = top_ranked[0][0]
                confidence = round(top_ranked[0][1], 2)
                ranked.append(
                    {
                        "department_id": str(primary_dept.id),
                        "department_name": primary_dept.name,
                        "confidence": confidence,
                        "reasons": [f"Zero-shot classifier ({top_ranked[0][2]}: {confidence:.0%})"],
                    }
                )
                for dept_obj, conf_val, ext_name in top_ranked[1:3]:
                    ranked.append(
                        {
                            "department_id": str(dept_obj.id),
                            "department_name": dept_obj.name,
                            "confidence": round(conf_val, 2),
                            "reasons": [f"Secondary zero-shot candidate ({ext_name}: {round(conf_val, 2):.0%})"],
                        }
                    )

        if not ranked and matching_rules:
            best_rule = matching_rules[0]
            rule_version_used = best_rule.rule_version
            primary_dept = best_rule.department
            confidence = 0.94
            reason = f"Matched versioned routing rule v{best_rule.rule_version} for category '{inferred_category}'"
            if best_rule.ward_id:
                reason += f" in ward {complaint.ward_name}"
            ranked.append(
                {
                    "department_id": str(primary_dept.id),
                    "department_name": primary_dept.name,
                    "confidence": confidence,
                    "reasons": [reason],
                }
            )
        elif not ranked:
            # Fallback heuristic mapping
            def find_dept_by_keyword(kw: str) -> Department:
                for d in all_depts:
                    if kw.lower() in d.name.lower() or kw.lower() in d.code.lower():
                        return d
                return all_depts[0]

            if "water" in inferred_category.lower():
                primary_dept = find_dept_by_keyword("water")
            elif "electric" in inferred_category.lower():
                primary_dept = find_dept_by_keyword("elec")
            elif "sanitation" in inferred_category.lower() or "solid" in inferred_category.lower():
                primary_dept = find_dept_by_keyword("san")
            elif "drain" in inferred_category.lower():
                primary_dept = find_dept_by_keyword("drain")
            elif "park" in inferred_category.lower():
                primary_dept = find_dept_by_keyword("park")
            else:
                primary_dept = find_dept_by_keyword("road")

            confidence = 0.85
            ranked.append(
                {
                    "department_id": str(primary_dept.id),
                    "department_name": primary_dept.name,
                    "confidence": confidence,
                    "reasons": [f"Heuristic keyword matching on '{inferred_category}'"],
                }
            )

        # Fill top-2 and top-3 with other departments if not already filled
        if len(ranked) < 2:
            other_depts = [d for d in all_depts if d.id != primary_dept.id]
            if other_depts:
                ranked.append(
                    {
                        "department_id": str(other_depts[0].id),
                        "department_name": other_depts[0].name,
                        "confidence": round(confidence * 0.7, 2),
                        "reasons": ["Secondary department with potential co-jurisdiction"],
                    }
                )
            if len(other_depts) > 1:
                ranked.append(
                    {
                        "department_id": str(other_depts[1].id),
                        "department_name": other_depts[1].name,
                        "confidence": round(confidence * 0.4, 2),
                        "reasons": ["Tertiary department candidate"],
                    }
                )
            ranked.append(
                {
                    "department_id": str(other_depts[1].id),
                    "department_name": other_depts[1].name,
                    "confidence": round(confidence * 0.4, 2),
                    "reasons": ["Tertiary department candidate"],
                }
            )

        rec = RoutingRecommendation(
            complaint_id=complaint.id,
            rule_version_used=rule_version_used,
            primary_department_id=primary_dept.id,
            recommended_departments=ranked,
            confidence=confidence,
            recommendation_status="PENDING",
        )
        created = await self.repo.create_recommendation(rec)

        await self.audit_service.record_event(
            entity_type="routing_recommendation",
            entity_id=created.id,
            action="routing.recommendation_generated",
            new_state={
                "complaint_id": str(complaint_id),
                "primary_department": primary_dept.name,
                "confidence": confidence,
                "rule_version_used": rule_version_used,
            },
        )
        return RoutingRecommendationResponse.model_validate(created)

    async def get_latest_recommendation(
        self, complaint_id: uuid.UUID
    ) -> RoutingRecommendationResponse:
        rec = await self.repo.get_latest_recommendation(complaint_id)
        if not rec:
            # Auto-generate if not present
            return await self.generate_routing_recommendation(complaint_id)
        return RoutingRecommendationResponse.model_validate(rec)

    async def accept_routing(
        self, complaint_id: uuid.UUID, officer: User, payload: AcceptRoutingRequest
    ) -> RoutingRecommendationResponse:
        """Human officer accepts routing recommendation. Advances complaint to ROUTED."""
        rec = await self.repo.get_latest_recommendation(complaint_id)
        if not rec:
            await self.generate_routing_recommendation(complaint_id)
            rec = await self.repo.get_latest_recommendation(complaint_id)
            assert rec is not None

        now = datetime.now(timezone.utc)
        rec.recommendation_status = "ACCEPTED"
        rec.decided_by_id = officer.id
        rec.decided_at = now
        rec.decision_reason = payload.notes

        # Advance complaint status to ROUTED
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if complaint:
            complaint.status = "ROUTED"

        # Ensure or link to Case
        try:
            from app.modules.cases.models.case import Case, CaseDepartment, CaseComplaint
            from app.modules.cases.repository.case_repository import CaseRepository
            case_repo = CaseRepository(self.session)
            case = await case_repo.get_case_for_complaint(complaint_id)
            target_dept_id = rec.primary_department_id
            if not case and complaint:
                case_number = f"CASE-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                case = Case(
                    id=uuid.uuid4(),
                    case_number=case_number,
                    title=f"Case: {complaint.original_title}",
                    description=complaint.original_description,
                    status="ROUTED",
                    priority="MEDIUM",
                    lead_department_id=target_dept_id,
                    created_by_id=officer.id,
                )
                self.session.add(case)
                await self.session.flush()
                cd = CaseDepartment(case_id=case.id, department_id=target_dept_id, is_lead=True, added_by_id=officer.id)
                self.session.add(cd)
                cc = CaseComplaint(case_id=case.id, complaint_id=complaint.id, is_primary=True)
                self.session.add(cc)
            elif case:
                case.status = "ROUTED"
                if target_dept_id:
                    case.lead_department_id = target_dept_id
        except Exception as c_err:
            logger.debug("Case link during accept_routing: %s", c_err)

        await self.audit_service.record_event(
            entity_type="routing_recommendation",
            entity_id=rec.id,
            action="routing.accepted",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "primary_department_id": str(rec.primary_department_id),
                "status": "ACCEPTED",
                "notes": payload.notes,
            },
        )
        return RoutingRecommendationResponse.model_validate(rec)

    async def override_routing(
        self, complaint_id: uuid.UUID, officer: User, payload: OverrideRoutingRequest
    ) -> RoutingRecommendationResponse:
        """Human officer overrides routing with mandatory justification. Advances complaint to ROUTED."""
        if not payload.reason or len(payload.reason.strip()) < 5:
            raise BadRequestError(
                "A substantive reason of at least 5 characters is required to override routing.",
                code="OVERRIDE_REASON_REQUIRED",
            )

        rec = await self.repo.get_latest_recommendation(complaint_id)
        if not rec:
            await self.generate_routing_recommendation(complaint_id)
            rec = await self.repo.get_latest_recommendation(complaint_id)
            assert rec is not None

        now = datetime.now(timezone.utc)
        rec.recommendation_status = "OVERRIDDEN"
        rec.primary_department_id = payload.department_id
        rec.decided_by_id = officer.id
        rec.decided_at = now
        rec.decision_reason = payload.reason.strip()

        # Advance complaint status to ROUTED
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if complaint:
            complaint.status = "ROUTED"

        # Ensure or link to Case
        try:
            from app.modules.cases.models.case import Case, CaseDepartment, CaseComplaint
            from app.modules.cases.repository.case_repository import CaseRepository
            case_repo = CaseRepository(self.session)
            case = await case_repo.get_case_for_complaint(complaint_id)
            if not case and complaint:
                case_number = f"CASE-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                case = Case(
                    id=uuid.uuid4(),
                    case_number=case_number,
                    title=f"Case: {complaint.original_title}",
                    description=complaint.original_description,
                    status="ROUTED",
                    priority="MEDIUM",
                    lead_department_id=payload.department_id,
                    created_by_id=officer.id,
                )
                self.session.add(case)
                await self.session.flush()
                cd = CaseDepartment(case_id=case.id, department_id=payload.department_id, is_lead=True, added_by_id=officer.id)
                self.session.add(cd)
                cc = CaseComplaint(case_id=case.id, complaint_id=complaint.id, is_primary=True)
                self.session.add(cc)
            elif case:
                case.status = "ROUTED"
                case.lead_department_id = payload.department_id
        except Exception as c_err:
            logger.debug("Case link during override_routing: %s", c_err)

        await self.audit_service.record_event(
            entity_type="routing_recommendation",
            entity_id=rec.id,
            action="routing.overridden",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "primary_department_id": str(payload.department_id),
                "reason": payload.reason.strip(),
                "status": "OVERRIDDEN",
            },
        )
        return RoutingRecommendationResponse.model_validate(rec)

    async def reject_routing(
        self, complaint_id: uuid.UUID, officer: User, payload: RejectRoutingRequest
    ) -> RoutingRecommendationResponse:
        """Human officer rejects routing recommendation with mandatory reason."""
        if not payload.reason or len(payload.reason.strip()) < 5:
            raise BadRequestError(
                "A substantive reason of at least 5 characters is required to reject routing.",
                code="REJECTION_REASON_REQUIRED",
            )

        rec = await self.repo.get_latest_recommendation(complaint_id)
        if not rec:
            await self.generate_routing_recommendation(complaint_id)
            rec = await self.repo.get_latest_recommendation(complaint_id)
            assert rec is not None

        now = datetime.now(timezone.utc)
        rec.recommendation_status = "REJECTED"
        rec.decided_by_id = officer.id
        rec.decided_at = now
        rec.decision_reason = payload.reason.strip()

        # Rejection sends complaint to MANUAL_TRIAGE (does NOT advance to ROUTED)
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if complaint:
            complaint.status = "MANUAL_TRIAGE"

        await self.audit_service.record_event(
            entity_type="routing_recommendation",
            entity_id=rec.id,
            action="routing.rejected",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "status": "REJECTED",
                "reason": payload.reason.strip(),
            },
        )
        return RoutingRecommendationResponse.model_validate(rec)
