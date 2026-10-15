import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.activity.models.activity import CaseActivity
from app.modules.cases.models.case import Case, CaseComplaint, CaseDepartment
from app.modules.challenges.models.challenge import (
    CitizenChallenge,
    ReopenEvent,
    ResolutionProposal,
)
from app.modules.complaints.models.complaint import Attachment, Complaint
from app.modules.identity.models.user import Department, User
from app.modules.identity.schemas.identity import UserRole


@pytest.fixture
async def sample_department(db_session: AsyncSession) -> Department:
    dept = Department(
        id=uuid.uuid4(),
        name="Roads & Infrastructure",
        code=f"ROADS-{uuid.uuid4().hex[:4].upper()}",
        is_active=True,
    )
    db_session.add(dept)
    await db_session.commit()
    await db_session.refresh(dept)
    return dept


@pytest.fixture
async def in_progress_case(
    db_session: AsyncSession,
    citizen_user: User,
    officer_user: User,
    sample_department: Department,
) -> Case:
    # 1. Create Complaint
    comp = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="Critical Pothole on 5th Main",
        original_description="Deep crater damaging vehicles.",
        original_language="en",
        latitude=12.9716,
        longitude=77.5946,
        address="5th Main Road",
        status="IN_PROGRESS",
    )
    db_session.add(comp)
    await db_session.flush()

    # 2. Create Case in IN_PROGRESS
    case = Case(
        id=uuid.uuid4(),
        case_number=f"CASE-{uuid.uuid4().hex[:6].upper()}",
        title="Pothole Remediation 5th Main",
        description="Deep crater repair assigned to field team.",
        status="IN_PROGRESS",
        priority="HIGH",
        lead_department_id=sample_department.id,
        assigned_officer_id=officer_user.id,
        created_by_id=officer_user.id,
    )
    db_session.add(case)
    await db_session.flush()

    cd = CaseDepartment(
        case_id=case.id,
        department_id=sample_department.id,
        is_lead=True,
        added_by_id=officer_user.id,
    )
    db_session.add(cd)

    cc = CaseComplaint(
        case_id=case.id,
        complaint_id=comp.id,
        is_primary=True,
    )
    db_session.add(cc)

    # Initial Case Activity
    act = CaseActivity(
        case_id=case.id,
        actor_id=officer_user.id,
        activity_type="OFFICER_ASSIGNED",
        visibility="CITIZEN_VISIBLE",
        message="Work commenced by assigned officer.",
    )
    db_session.add(act)

    await db_session.commit()
    await db_session.refresh(case)
    return case


@pytest.fixture
async def evidence_attachment(
    db_session: AsyncSession,
    officer_user: User,
    in_progress_case: Case,
) -> Attachment:
    att = Attachment(
        id=uuid.uuid4(),
        case_id=in_progress_case.id,
        uploader_id=officer_user.id,
        file_url="https://storage.municipality.gov/evidence/repaired_pothole.jpg",
        file_name="repaired_pothole.jpg",
        mime_type="image/jpeg",
        file_size_bytes=1024 * 512,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        attachment_type="RESOLUTION_PROOF",
    )
    db_session.add(att)
    await db_session.commit()
    await db_session.refresh(att)
    return att


@pytest.fixture
async def independent_supervisor(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="indep.supervisor@example.com",
        phone_number="+15550099",
        password_hash=hash_password("Password123!"),
        role=UserRole.SUPERVISOR.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def independent_supervisor_token(independent_supervisor: User) -> str:
    return create_access_token(
        subject=str(independent_supervisor.id), role=independent_supervisor.role
    )


# ========================================================
# 1. Closure Without Evidence is Rejected
# ========================================================


@pytest.mark.asyncio
async def test_closure_without_evidence_is_rejected(
    client: AsyncClient,
    citizen_token: str,
    officer_token: str,
    in_progress_case: Case,
) -> None:
    """Invariant: Case can NEVER be closed without verified evidence attachments."""
    # 1. Attempting to confirm closure when no proposal/evidence exists must fail
    res_confirm = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/confirm",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={"feedback": "Looks good to me!"},
    )
    assert res_confirm.status_code == 400
    assert res_confirm.json()["code"] == "EVIDENCE_REQUIRED"

    # 2. Submitting resolution proposal with empty attachment list must be rejected
    res_empty_att = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/resolve",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "remediation_summary": "Asphalt patched completely.",
            "attachment_ids": [],
            "review_window_days": 7,
        },
    )
    assert res_empty_att.status_code == 422

    # 3. Direct transition to CLOSED via state machine endpoint without evidence must fail
    res_trans = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/transition",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"target_state": "CLOSED", "reason": "Bypassing evidence requirement"},
    )
    assert res_trans.status_code == 400


# ========================================================
# 2. Review Window Expiry Closes Case
# ========================================================


@pytest.mark.asyncio
async def test_review_window_expiry_closes_case(
    client: AsyncClient,
    officer_token: str,
    supervisor_token: str,
    citizen_token: str,
    in_progress_case: Case,
    evidence_attachment: Attachment,
    db_session: AsyncSession,
) -> None:
    """Worker Job: When review window expires with no challenge, case is automatically closed."""
    # 1. Officer submits resolution proposal with valid evidence attachment
    res_resolve = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/resolve",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "remediation_summary": "Filled pothole with bitumen layer and steamrolled smooth.",
            "root_cause_identified": "Heavy monsoon rainwater accumulation.",
            "attachment_ids": [str(evidence_attachment.id)],
            "review_window_days": 7,
        },
    )
    assert res_resolve.status_code == 201
    prop_data = res_resolve.json()
    assert prop_data["officer_verified"] is True
    assert prop_data["status"] == "PROPOSED"

    # Verify case transitioned to CITIZEN_REVIEW
    stmt_case = select(Case).where(Case.id == in_progress_case.id)
    case_db = (await db_session.execute(stmt_case)).scalar_one()
    assert case_db.status == "CITIZEN_REVIEW"

    # 2. Manually expire review window in the database (simulate 8 days elapsed)
    stmt_prop = select(ResolutionProposal).where(ResolutionProposal.case_id == in_progress_case.id)
    proposal_db = (await db_session.execute(stmt_prop)).scalar_one()
    proposal_db.review_window_expires_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db_session.commit()

    # 3. Trigger review-window expiry worker job
    res_worker = await client.post(
        "/api/v1/cases/worker/expire-review-windows",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert res_worker.status_code == 200
    closed_ids = res_worker.json()
    assert str(in_progress_case.id) in closed_ids

    # 4. Verify case is now CLOSED and proposal is AUTO_CLOSED
    await db_session.refresh(case_db)
    await db_session.refresh(proposal_db)
    assert case_db.status == "CLOSED"
    assert proposal_db.status == "AUTO_CLOSED"

    # 5. Verify citizen timeline reflects CASE_CLOSED
    # First get linked complaint id
    complaint_id = in_progress_case.case_complaints[0].complaint_id
    res_timeline = await client.get(
        f"/api/v1/cases/citizen-timeline/{complaint_id}",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert res_timeline.status_code == 200
    timeline = res_timeline.json()
    activity_types = [item["activity_type"] for item in timeline]
    assert "CASE_CLOSED" in activity_types


# ========================================================
# 3. Self-Review is Blocked
# ========================================================


@pytest.mark.asyncio
async def test_self_review_is_blocked(
    client: AsyncClient,
    officer_token: str,
    officer_user: User,
    citizen_token: str,
    independent_supervisor_token: str,
    in_progress_case: Case,
    evidence_attachment: Attachment,
    db_session: AsyncSession,
) -> None:
    """Anti-Self-Review: Any actor in the original chain of action is barred from reviewing the dispute."""
    # 1. Officer proposes resolution
    res_resolve = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/resolve",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "remediation_summary": "Pothole filled with loose gravel temporarily.",
            "attachment_ids": [str(evidence_attachment.id)],
            "review_window_days": 7,
        },
    )
    assert res_resolve.status_code == 201

    # 2. Citizen disputes resolution within review window
    res_challenge = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/challenge",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={
            "challenge_type": "RESOLUTION",
            "reason": "Loose gravel was washed away by light rain; the road is still hazardous.",
            "attachment_ids": [],
        },
    )
    assert res_challenge.status_code == 201
    challenge_id = res_challenge.json()["id"]

    # 3. Grant the proposing officer supervisor role in DB to demonstrate that even with
    # supervisor privileges, because they were in the chain of action, self-review is strictly blocked!
    officer_user.role = UserRole.SUPERVISOR.value
    await db_session.commit()
    await db_session.refresh(officer_user)

    rogue_officer_supervisor_token = create_access_token(
        subject=str(officer_user.id), role=UserRole.SUPERVISOR.value
    )

    res_self_review = await client.post(
        f"/api/v1/challenges/{challenge_id}/review",
        headers={"Authorization": f"Bearer {rogue_officer_supervisor_token}"},
        json={
            "verdict": "UPHELD",
            "rationale": "I inspected my own work and confirmed it was adequate.",
        },
    )
    assert res_self_review.status_code == 403
    assert res_self_review.json()["code"] == "SELF_REVIEW_BLOCKED"

    # 4. An independent supervisor with NO previous involvement can successfully review
    res_independent_review = await client.post(
        f"/api/v1/challenges/{challenge_id}/review",
        headers={"Authorization": f"Bearer {independent_supervisor_token}"},
        json={
            "verdict": "OVERTURNED",
            "rationale": "Inspection shows loose gravel is uncompacted. Official resolution overturned.",
            "action_taken": "Reopened case for hot-mix asphalt remediation.",
        },
    )
    assert res_independent_review.status_code == 200
    assert res_independent_review.json()["status"] == "OVERTURNED"


# ========================================================
# 4. Overturn Reopens Case & Logs ReopenEvent
# ========================================================


@pytest.mark.asyncio
async def test_overturn_reopens_case_and_logs_event(
    client: AsyncClient,
    officer_token: str,
    citizen_token: str,
    independent_supervisor_token: str,
    in_progress_case: Case,
    evidence_attachment: Attachment,
    db_session: AsyncSession,
) -> None:
    """Overturned Challenge: Generates ReopenEvent, moves case REOPENED -> IN_PROGRESS."""
    # 1. Propose resolution
    await client.post(
        f"/api/v1/cases/{in_progress_case.id}/resolve",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "remediation_summary": "Patch applied.",
            "attachment_ids": [str(evidence_attachment.id)],
            "review_window_days": 7,
        },
    )

    # 2. Citizen challenges
    res_chal = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/challenge",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={
            "challenge_type": "RESOLUTION",
            "reason": "Defective patch broken within 24 hours.",
        },
    )
    challenge_id = res_chal.json()["id"]

    # 3. Independent supervisor overturns resolution
    res_review = await client.post(
        f"/api/v1/challenges/{challenge_id}/review",
        headers={"Authorization": f"Bearer {independent_supervisor_token}"},
        json={
            "verdict": "OVERTURNED",
            "rationale": "Field audit confirmed patch failure. Overturning resolution.",
            "action_taken": "Instructed road crew to re-mill and re-asphalt.",
        },
    )
    assert res_review.status_code == 200
    assert res_review.json()["status"] == "OVERTURNED"

    # 4. Verify ReopenEvent is logged in DB
    stmt_reopen = select(ReopenEvent).where(ReopenEvent.case_id == in_progress_case.id)
    reopen_record = (await db_session.execute(stmt_reopen)).scalar_one_or_none()
    assert reopen_record is not None
    assert reopen_record.trigger_source == "CHALLENGE_OVERTURNED"
    assert "Field audit confirmed" in reopen_record.reason

    # 5. Verify Case moved to IN_PROGRESS (via REOPENED)
    stmt_case = select(Case).where(Case.id == in_progress_case.id)
    case_db = (await db_session.execute(stmt_case)).scalar_one()
    assert case_db.status == "IN_PROGRESS"

    # 6. Verify Citizen Timeline contains CASE_REOPENED and WORK_RESUMED
    complaint_id = in_progress_case.case_complaints[0].complaint_id
    res_timeline = await client.get(
        f"/api/v1/cases/citizen-timeline/{complaint_id}",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert res_timeline.status_code == 200
    timeline_types = [item["activity_type"] for item in res_timeline.json()]
    assert "CASE_REOPENED" in timeline_types
    assert "WORK_RESUMED" in timeline_types


# ========================================================
# 5. SLA Timer Breach Automatically Escalates
# ========================================================


@pytest.mark.asyncio
async def test_challenge_sla_escalation(
    client: AsyncClient,
    officer_token: str,
    citizen_token: str,
    supervisor_token: str,
    in_progress_case: Case,
    evidence_attachment: Attachment,
    db_session: AsyncSession,
) -> None:
    """Worker Job: Overdue challenge exceeding SLA is automatically escalated."""
    # 1. Setup resolution & challenge
    await client.post(
        f"/api/v1/cases/{in_progress_case.id}/resolve",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "remediation_summary": "Surface leveled.",
            "attachment_ids": [str(evidence_attachment.id)],
            "review_window_days": 7,
        },
    )
    res_chal = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/challenge",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={
            "challenge_type": "RESOLUTION",
            "reason": "Uneven road surface causing bike skids.",
        },
    )
    challenge_id = uuid.UUID(res_chal.json()["id"])

    # 2. Fast-forward SLA timer past 48 hours
    stmt_chal = select(CitizenChallenge).where(CitizenChallenge.id == challenge_id)
    challenge_db = (await db_session.execute(stmt_chal)).scalar_one()
    assert challenge_db.is_escalated is False

    # Simulate SLA breach
    challenge_db.sla_expires_at = datetime.now(timezone.utc) - timedelta(hours=3)
    await db_session.commit()

    # 3. Run SLA escalation job
    res_worker = await client.post(
        "/api/v1/challenges/worker/sla-escalations",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert res_worker.status_code == 200
    escalated_ids = res_worker.json()
    assert str(challenge_id) in escalated_ids

    # 4. Verify challenge is escalated in database
    await db_session.refresh(challenge_db)
    assert challenge_db.is_escalated is True
    assert challenge_db.escalated_at is not None

    # 5. Verify Case Activity logged CHALLENGE_ESCALATED
    stmt_act = select(CaseActivity).where(
        CaseActivity.case_id == in_progress_case.id,
        CaseActivity.activity_type == "CHALLENGE_ESCALATED",
    )
    act_record = (await db_session.execute(stmt_act)).scalar_one_or_none()
    assert act_record is not None
    assert "breached review SLA" in act_record.message


# ========================================================
# 6. Citizen Confirmation Closes Case
# ========================================================


@pytest.mark.asyncio
async def test_citizen_confirmation_closes_case(
    client: AsyncClient,
    officer_token: str,
    citizen_token: str,
    in_progress_case: Case,
    evidence_attachment: Attachment,
    db_session: AsyncSession,
) -> None:
    """Citizen confirms satisfaction with verified evidence -> case closes."""
    # 1. Propose resolution
    await client.post(
        f"/api/v1/cases/{in_progress_case.id}/resolve",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "remediation_summary": "Pothole completely re-tarred and leveled.",
            "attachment_ids": [str(evidence_attachment.id)],
            "review_window_days": 7,
        },
    )

    # 2. Citizen confirms resolution
    res_confirm = await client.post(
        f"/api/v1/cases/{in_progress_case.id}/confirm",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={"feedback": "The street is completely smooth now. Thank you!"},
    )
    assert res_confirm.status_code == 200
    assert res_confirm.json()["status"] == "CLOSED"

    # 3. Verify in database
    stmt_case = select(Case).where(Case.id == in_progress_case.id)
    case_db = (await db_session.execute(stmt_case)).scalar_one()
    assert case_db.status == "CLOSED"


# ========================================================
# 7. Citizen Queries Challenge Status & Queue
# ========================================================


@pytest.mark.asyncio
async def test_challenge_status_and_staff_queue(
    client: AsyncClient,
    officer_token: str,
    citizen_token: str,
    supervisor_token: str,
    in_progress_case: Case,
    evidence_attachment: Attachment,
) -> None:
    """Citizen queries challenge status and staff inspects queue."""
    # 1. Propose and challenge
    await client.post(
        f"/api/v1/cases/{in_progress_case.id}/resolve",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "remediation_summary": "Surface leveled.",
            "attachment_ids": [str(evidence_attachment.id)],
            "review_window_days": 7,
        },
    )
    await client.post(
        f"/api/v1/cases/{in_progress_case.id}/challenge",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={
            "challenge_type": "RESOLUTION",
            "reason": "Water is already pooling in the patch area.",
        },
    )

    # 2. Citizen queries latest challenge status for their case
    res_status = await client.get(
        f"/api/v1/cases/{in_progress_case.id}/challenge",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert res_status.status_code == 200
    assert res_status.json()["status"] == "PENDING"
    assert "Water is already pooling" in res_status.json()["reason"]

    # 3. Staff queries queue
    res_queue = await client.get(
        "/api/v1/challenges/queue?status=PENDING",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert res_queue.status_code == 200
    queue = res_queue.json()
    assert any(item["case_id"] == str(in_progress_case.id) for item in queue)
