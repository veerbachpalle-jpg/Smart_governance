import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.chaos import DBInjectedChaosError, chaos_manager
from app.core.outbox import DeadLetterEvent, OutboxEvent, outbox_processor
from app.modules.activity.models.activity import CaseActivity
from app.modules.ai_assist.models.ai_interpretation import AIInterpretation
from app.modules.ai_assist.service.ai_service import AIAssistService
from app.modules.audit.models.audit import AuditEvent
from app.modules.cases.models.case import Case, CaseComplaint, CaseDepartment
from app.modules.cases.service.state_machine import CaseStateMachine
from app.modules.complaints.models.complaint import Complaint
from app.modules.identity.models.user import Department, User
from app.modules.notifications.service.notification_service import NotificationService
from app.modules.priority.models.priority import PriorityAssessment
from app.modules.routing.models.routing import RoutingRecommendation


@pytest.fixture(autouse=True)
def reset_chaos_after_test():
    """Ensure chaos manager is clean before and after every test."""
    chaos_manager.reset()
    yield
    chaos_manager.reset()


@pytest.fixture
async def sample_department(db_session: AsyncSession) -> Department:
    dept = Department(
        id=uuid.uuid4(),
        name="Electrical & Street Lighting",
        code=f"ELEC-{uuid.uuid4().hex[:4].upper()}",
        is_active=True,
    )
    db_session.add(dept)
    await db_session.commit()
    await db_session.refresh(dept)
    return dept


@pytest.fixture
async def triage_complaint(
    db_session: AsyncSession,
    citizen_user: User,
) -> Complaint:
    comp = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-CHAOS-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="Streetlight outage creating darkness",
        original_description="Street light pole #44 is completely dark for three nights.",
        original_language="en",
        latitude=12.9300,
        longitude=77.5800,
        address="12th Main Indiranagar",
        status="SUBMITTED",
    )
    db_session.add(comp)
    await db_session.commit()
    await db_session.refresh(comp)
    return comp


@pytest.fixture
async def active_case(
    db_session: AsyncSession,
    officer_user: User,
    triage_complaint: Complaint,
    sample_department: Department,
) -> Case:
    case = Case(
        id=uuid.uuid4(),
        case_number=f"CASE-CHAOS-{uuid.uuid4().hex[:6].upper()}",
        title="Streetlight outage",
        description="Fix street light pole #44",
        status="IN_PROGRESS",
        priority="MEDIUM",
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
        complaint_id=triage_complaint.id,
        is_primary=True,
    )
    db_session.add(cc)

    act = CaseActivity(
        case_id=case.id,
        actor_id=officer_user.id,
        activity_type="OFFICER_ASSIGNED",
        visibility="CITIZEN_VISIBLE",
        message="Officer assigned to repair streetlight.",
    )
    db_session.add(act)

    await db_session.commit()
    await db_session.refresh(case)
    return case


# ========================================================
# Scenario 1: AI Down -> Falls back to MANUAL_TRIAGE -> Manual Triage Workflow
# ========================================================


@pytest.mark.asyncio
async def test_scenario_ai_down_preserves_records_and_enables_manual_triage(
    client: AsyncClient,
    admin_token: str,
    officer_token: str,
    officer_user: User,
    triage_complaint: Complaint,
    sample_department: Department,
    db_session: AsyncSession,
) -> None:
    """Proves: When AI is down, no complaint or audit record is lost; degrades to MANUAL_TRIAGE; officer manually triages with source=MANUAL."""
    # 1. Admin activates chaos: disable AI
    res_chaos = await client.post(
        "/api/v1/admin/chaos",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"disable_ai": True},
    )
    assert res_chaos.status_code == 200
    assert res_chaos.json()["disable_ai"] is True
    assert res_chaos.json()["is_active"] is True

    # 2. Worker executes triage pipeline under AI down conditions
    ai_service = AIAssistService(db_session)
    result = await ai_service.execute_triage_pipeline(triage_complaint.id)
    assert result is None  # Gracefully degraded

    # Verify complaint degraded to MANUAL_TRIAGE without data loss
    await db_session.refresh(triage_complaint)
    assert triage_complaint.status == "MANUAL_TRIAGE"

    # Verify audit trail recorded fallback
    stmt_audit = select(AuditEvent).where(
        AuditEvent.entity_id == triage_complaint.id,
        AuditEvent.action == "complaint.manual_triage_fallback",
    )
    audit_fallback = (await db_session.execute(stmt_audit)).scalar_one_or_none()
    assert audit_fallback is not None

    # 3. Officer queries manual triage queue
    res_queue = await client.get(
        "/api/v1/triage/manual/queue",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert res_queue.status_code == 200
    queue = res_queue.json()
    assert any(item["id"] == str(triage_complaint.id) for item in queue)

    # 4. Officer enters manual triage with category, routing and priority
    res_triage = await client.post(
        f"/api/v1/triage/manual/{triage_complaint.id}",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "category": "Street Lighting",
            "sub_category": "Bulb Replacement",
            "department_id": str(sample_department.id),
            "priority": "HIGH",
            "notes": "Manual triage: Dark alley poses pedestrian safety hazard.",
        },
    )
    assert res_triage.status_code == 200
    triage_data = res_triage.json()
    assert triage_data["source"] == "MANUAL"
    assert triage_data["status"] == "ROUTED"
    assert triage_data["category"] == "Street Lighting"
    assert triage_data["priority"] == "HIGH"

    # 5. Verify all downstream records exist and are marked source=MANUAL
    # a) AIInterpretation
    stmt_interp = select(AIInterpretation).where(
        AIInterpretation.id == uuid.UUID(triage_data["ai_interpretation_id"])
    )
    interp_rec = (await db_session.execute(stmt_interp)).scalar_one()
    assert interp_rec.parsed_output.get("source") == "MANUAL"
    assert interp_rec.confidence == 1.0

    # b) RoutingRecommendation
    stmt_routing = select(RoutingRecommendation).where(
        RoutingRecommendation.id == uuid.UUID(triage_data["routing_recommendation_id"])
    )
    routing_rec = (await db_session.execute(stmt_routing)).scalar_one()
    assert routing_rec.recommended_departments[0].get("source") == "MANUAL"

    # c) PriorityAssessment
    stmt_priority = select(PriorityAssessment).where(
        PriorityAssessment.id == uuid.UUID(triage_data["priority_assessment_id"])
    )
    priority_rec = (await db_session.execute(stmt_priority)).scalar_one()
    assert priority_rec.rule_hits[0].get("source") == "MANUAL"

    # d) Case & Activity
    case_id = uuid.UUID(triage_data["case_id"])
    stmt_act = select(CaseActivity).where(
        CaseActivity.case_id == case_id,
        CaseActivity.activity_type == "CASE_ROUTED",
    )
    act_rec = (await db_session.execute(stmt_act)).scalar_one()
    assert act_rec.activity_metadata.get("source") == "MANUAL"


# ========================================================
# Scenario 2: AI Garbage -> Degradation to MANUAL_TRIAGE
# ========================================================


@pytest.mark.asyncio
async def test_scenario_ai_garbage_falls_back_to_manual_triage(
    client: AsyncClient,
    admin_token: str,
    triage_complaint: Complaint,
    db_session: AsyncSession,
) -> None:
    """Proves: When AI returns garbage/corrupted output, retries exhaust and it degrades gracefully to MANUAL_TRIAGE."""
    # 1. Admin configures AI garbage simulation
    res_chaos = await client.post(
        "/api/v1/admin/chaos",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"ai_garbage": True},
    )
    assert res_chaos.status_code == 200
    assert res_chaos.json()["ai_garbage"] is True

    # 2. Run triage pipeline
    ai_service = AIAssistService(db_session)
    result = await ai_service.execute_triage_pipeline(triage_complaint.id)
    assert result is None

    # 3. Verify complaint status degraded to MANUAL_TRIAGE without crashing
    await db_session.refresh(triage_complaint)
    assert triage_complaint.status == "MANUAL_TRIAGE"

    # 4. Verify audit entry records the garbage/parse failure
    stmt_audit = select(AuditEvent).where(
        AuditEvent.entity_id == triage_complaint.id,
        AuditEvent.action == "complaint.manual_triage_fallback",
    )
    audit_entry = (await db_session.execute(stmt_audit)).scalar_one_or_none()
    assert audit_entry is not None
    assert "error" in audit_entry.new_state


# ========================================================
# Scenario 3: Worker killed mid-job and restarted (idempotent outbox reprocessing)
# ========================================================


@pytest.mark.asyncio
async def test_scenario_worker_killed_and_restarted_idempotent(
    db_session: AsyncSession,
    triage_complaint: Complaint,
) -> None:
    """Proves: When worker halts/dies mid-job and restarts, outbox is reprocessed idempotently with no duplicate effects."""
    execution_counter = 0

    async def side_effect_handler(event: OutboxEvent, session: AsyncSession) -> None:
        nonlocal execution_counter
        execution_counter += 1
        if execution_counter == 1:
            # Simulate worker process crash/kill mid-job before committing event status
            raise RuntimeError("SIGKILL: Worker killed mid-job by supervisor!")

    event_type = f"test.worker.kill.{uuid.uuid4().hex[:6]}"
    outbox_processor.register_handler(event_type, side_effect_handler)

    # 1. Enqueue outbox event
    event = await outbox_processor.enqueue_event(
        session=db_session,
        event_type=event_type,
        aggregate_type="complaint",
        aggregate_id=triage_complaint.id,
        payload={"complaint_id": str(triage_complaint.id)},
        max_retries=5,
    )
    await db_session.commit()

    # 2. First worker execution: crashes mid-job
    await outbox_processor.process_batch(db_session)
    await db_session.refresh(event)
    assert event.status == "PENDING"
    assert event.retry_count == 1

    # Clear retry backoff to simulate instant worker restart
    event.next_retry_at = None
    await db_session.commit()

    # 3. Worker restarted: reprocesses outbox event
    processed = await outbox_processor.process_batch(db_session)
    await db_session.refresh(event)
    assert processed == 1
    assert event.status == "PUBLISHED"

    # 4. Third invocation with same event: Idempotency check prevents duplicate side effects
    re_processed = await outbox_processor.process_batch(db_session)
    assert re_processed == 0
    # The handler was only called twice (1st crash + 2nd success); 3rd call ignored
    assert execution_counter == 2


# ========================================================
# Scenario 4: Notification Failure -> Retries -> Dead Letter; Case State Unaffected
# ========================================================


@pytest.mark.asyncio
async def test_scenario_notification_failure_does_not_affect_case_state(
    client: AsyncClient,
    admin_token: str,
    active_case: Case,
    db_session: AsyncSession,
) -> None:
    """Proves: Notification channel failure retries, dead-letters, and NEVER affects case state mutation or audit integrity."""
    # 1. Activate notification failure chaos
    res_chaos = await client.post(
        "/api/v1/admin/chaos",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"fail_notifications": True},
    )
    assert res_chaos.status_code == 200
    assert res_chaos.json()["fail_notifications"] is True

    notif_service = NotificationService(db_session)

    # 2. Trigger safe case notification during workflow
    log_entry = await notif_service.notify_case_event_safely(
        case_id=active_case.id,
        event_type="CASE_STATUS_CHANGED",
        recipient="citizen.test@example.com",
        title="Your grievance status has been updated",
        message="Work is currently progressing on your streetlight issue.",
    )
    await db_session.commit()

    # 3. Verify notification failed and exhausted retries to DEAD_LETTER
    assert log_entry is not None
    assert log_entry.status == "DEAD_LETTER"
    assert log_entry.retry_count == 3

    # 4. Verify dead_letter_events table captured the dead-lettered notification
    stmt_dl = select(DeadLetterEvent).where(
        DeadLetterEvent.aggregate_id == log_entry.id,
        DeadLetterEvent.aggregate_type == "notification_log",
    )
    dl_record = (await db_session.execute(stmt_dl)).scalar_one_or_none()
    assert dl_record is not None
    assert "Simulated delivery channel fault" in dl_record.failure_reason

    # 5. CRITICAL INVARIANT: Verify case state remains completely intact and unaffected
    stmt_case = select(Case).where(Case.id == active_case.id)
    case_db = (await db_session.execute(stmt_case)).scalar_one()
    assert case_db.status == "IN_PROGRESS"

    # Case activities and audit trail remain completely valid
    stmt_acts = select(CaseActivity).where(CaseActivity.case_id == active_case.id)
    acts = list((await db_session.execute(stmt_acts)).scalars().all())
    assert len(acts) >= 1


# ========================================================
# Scenario 5: Injected DB Error Rolls Back Cleanly and Client Retries
# ========================================================


@pytest.mark.asyncio
async def test_scenario_injected_db_error_rolls_back_and_allows_retry(
    client: AsyncClient,
    admin_token: str,
    officer_user: User,
    active_case: Case,
    db_session: AsyncSession,
) -> None:
    """Proves: Injected DB error rolls back transaction cleanly with zero orphan state; client can safely retry."""
    # 1. Configure chaos: inject DB error into "case.transition"
    res_chaos = await client.post(
        "/api/v1/admin/chaos",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"db_error_operations": ["case.transition"]},
    )
    assert res_chaos.status_code == 200
    assert "case.transition" in res_chaos.json()["db_error_operations"]

    case_id = active_case.id
    officer_id = officer_user.id

    # 2. Attempt case transition -> Injected DB error occurs
    state_machine = CaseStateMachine(db_session)
    with pytest.raises(DBInjectedChaosError) as exc_info:
        await state_machine.transition(
            case=active_case,
            target_state="REASSIGN_REQUESTED",
            actor=officer_user,
            reason="Misrouted to electric department; road structure team needed.",
        )
    assert "Simulated database fault" in str(exc_info.value.detail)

    # 3. Roll back session and verify clean state
    await db_session.rollback()

    from app.modules.cases.repository.case_repository import CaseRepository

    case_repo = CaseRepository(db_session)
    case_after_fail = await case_repo.get_case_by_id(case_id)
    assert case_after_fail is not None
    # Case was NOT changed to REASSIGN_REQUESTED; pristine in IN_PROGRESS
    assert case_after_fail.status == "IN_PROGRESS"

    # Reload officer user after rollback
    stmt_user = select(User).where(User.id == officer_id)
    fresh_officer = (await db_session.execute(stmt_user)).scalar_one()

    # No orphan audit event was committed
    stmt_audit = select(AuditEvent).where(
        AuditEvent.entity_id == case_id,
        AuditEvent.action == "case.reassign_requested",
    )
    audit_orphan = (await db_session.execute(stmt_audit)).scalar_one_or_none()
    assert audit_orphan is None

    # 4. Clear chaos simulation
    res_reset = await client.post(
        "/api/v1/admin/chaos/reset",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_reset.status_code == 200
    assert res_reset.json()["is_active"] is False

    # 5. Client retries transition -> Succeeds cleanly!
    updated_case = await state_machine.transition(
        case=case_after_fail,
        target_state="REASSIGN_REQUESTED",
        actor=fresh_officer,
        reason="Misrouted to electric department; road structure team needed.",
    )
    await db_session.commit()

    assert updated_case.status == "REASSIGN_REQUESTED"
    stmt_audit_retry = select(AuditEvent).where(
        AuditEvent.entity_id == active_case.id,
        AuditEvent.action == "case.reassign_requested",
    )
    audit_valid = (await db_session.execute(stmt_audit_retry)).scalar_one_or_none()
    assert audit_valid is not None


# ========================================================
# Scenario 6: Production Refusal Invariant
# ========================================================


@pytest.mark.asyncio
async def test_chaos_refuses_to_run_in_production(
    client: AsyncClient,
    admin_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariant: Chaos endpoints must strictly reject execution when ENV=production."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    res_get = await client.get(
        "/api/v1/admin/chaos",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_get.status_code == 403
    assert res_get.json()["code"] == "CHAOS_FORBIDDEN_IN_PRODUCTION"

    res_post = await client.post(
        "/api/v1/admin/chaos",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"disable_ai": True},
    )
    assert res_post.status_code == 403
    assert res_post.json()["code"] == "CHAOS_FORBIDDEN_IN_PRODUCTION"
