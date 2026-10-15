import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.idempotency import IdempotencyManager
from app.core.outbox import DeadLetterEvent, OutboxEvent, outbox_processor
from app.modules.audit.schemas.audit import AuditFilterParams
from app.modules.audit.service.audit_service import AuditService

# ==========================================
# 1. Transactional Outbox Tests
# ==========================================


@pytest.mark.asyncio
async def test_outbox_enqueue_in_same_transaction(db_session: AsyncSession) -> None:
    aggregate_id = uuid.uuid4()
    event = await outbox_processor.enqueue_event(
        session=db_session,
        event_type="TestEntityCreated",
        aggregate_type="test_entity",
        aggregate_id=aggregate_id,
        payload={"message": "hello outbox"},
    )
    await db_session.commit()

    assert event.id is not None
    assert event.status == "PENDING"
    assert event.retry_count == 0


@pytest.mark.asyncio
async def test_outbox_successful_dispatch(db_session: AsyncSession) -> None:
    aggregate_id = uuid.uuid4()
    handled_events = []

    async def sample_handler(evt: OutboxEvent, session: AsyncSession) -> None:
        handled_events.append(evt.id)

    outbox_processor.register_handler("SampleEventPublished", sample_handler)

    event = await outbox_processor.enqueue_event(
        session=db_session,
        event_type="SampleEventPublished",
        aggregate_type="sample",
        aggregate_id=aggregate_id,
        payload={"key": "value"},
    )
    await db_session.commit()

    processed_count = await outbox_processor.process_batch(db_session)
    await db_session.commit()

    assert processed_count >= 1
    assert event.id in handled_events
    await db_session.refresh(event)
    assert event.status == "PUBLISHED"
    assert event.processed_at is not None


@pytest.mark.asyncio
async def test_outbox_retry_with_exponential_backoff(db_session: AsyncSession) -> None:
    async def failing_handler(evt: OutboxEvent, session: AsyncSession) -> None:
        raise RuntimeError("Transient connection failure")

    outbox_processor.register_handler("FailRetryEvent", failing_handler)

    event = await outbox_processor.enqueue_event(
        session=db_session,
        event_type="FailRetryEvent",
        aggregate_type="sample",
        aggregate_id=uuid.uuid4(),
        payload={"attempt": 1},
        max_retries=3,
    )
    await db_session.commit()

    # Process first attempt
    await outbox_processor.process_batch(db_session)
    await db_session.commit()
    await db_session.refresh(event)

    assert event.status == "PENDING"
    assert event.retry_count == 1
    assert event.next_retry_at is not None
    retry_at = (
        event.next_retry_at
        if event.next_retry_at.tzinfo
        else event.next_retry_at.replace(tzinfo=timezone.utc)
    )
    assert retry_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_outbox_dead_lettering(db_session: AsyncSession) -> None:
    async def fatal_handler(evt: OutboxEvent, session: AsyncSession) -> None:
        raise ValueError("Fatal payload error")

    outbox_processor.register_handler("FatalEvent", fatal_handler)

    event = await outbox_processor.enqueue_event(
        session=db_session,
        event_type="FatalEvent",
        aggregate_type="sample",
        aggregate_id=uuid.uuid4(),
        payload={"fatal": True},
        max_retries=1,
    )
    await db_session.commit()

    # First attempt fails and should trigger dead-lettering immediately
    await outbox_processor.process_batch(db_session)
    await db_session.commit()
    await db_session.refresh(event)

    assert event.status == "FAILED"
    assert event.retry_count == 1

    # Verify dead letter event row exists
    dl_stmt = select(DeadLetterEvent).where(DeadLetterEvent.outbox_event_id == event.id)
    dl_res = await db_session.execute(dl_stmt)
    dl_row = dl_res.scalar_one_or_none()
    assert dl_row is not None


# ==========================================
# 2. Append-Only Audit & Hash Chain Tests
# ==========================================


@pytest.mark.asyncio
async def test_audit_hash_chain_validity(db_session: AsyncSession) -> None:
    service = AuditService(db_session)

    # Record 5 sequential audit nodes
    for i in range(5):
        await service.record_event(
            entity_type="case",
            entity_id=uuid.uuid4(),
            action=f"status_updated_{i}",
            old_state={"step": i},
            new_state={"step": i + 1},
        )
    await db_session.commit()

    verify_res = await service.verify_chain()
    assert verify_res.is_valid is True
    assert verify_res.total_events >= 5


@pytest.mark.asyncio
async def test_audit_tamper_detection(db_session: AsyncSession) -> None:
    service = AuditService(db_session)

    # Record 3 events
    await service.record_event(entity_type="complaint", entity_id=uuid.uuid4(), action="created")
    ev2 = await service.record_event(
        entity_type="complaint", entity_id=uuid.uuid4(), action="reviewed"
    )
    await service.record_event(entity_type="complaint", entity_id=uuid.uuid4(), action="resolved")
    await db_session.commit()

    # Verify initially valid
    initial_check = await service.verify_chain()
    assert initial_check.is_valid is True

    # Tamper with row 2 using raw SQL (modifying action)
    await db_session.execute(
        text("UPDATE audit_events SET action = 'tampered_action' WHERE sequence_number = :seq"),
        {"seq": ev2.sequence_number},
    )
    await db_session.commit()
    db_session.expire_all()

    # Verification must detect the tampering
    tampered_check = await service.verify_chain()
    assert tampered_check.is_valid is False
    assert tampered_check.broken_at_sequence == ev2.sequence_number
    assert tampered_check.event_id == str(ev2.id)


@pytest.mark.asyncio
async def test_audit_immutability_blocks_orm(db_session: AsyncSession) -> None:
    service = AuditService(db_session)
    event = await service.record_event(entity_type="test", entity_id=uuid.uuid4(), action="create")
    await db_session.commit()

    # Attempting to mutate through ORM raises RuntimeError
    event.action = "illegal_update"
    with pytest.raises(RuntimeError) as exc_info:
        await db_session.commit()
    assert "append-only" in str(exc_info.value).lower()


# ==========================================
# 3. Idempotency-Key Tests
# ==========================================


@pytest.mark.asyncio
async def test_idempotency_manager_replay_and_conflict(db_session: AsyncSession) -> None:
    key = f"idem-key-{uuid.uuid4()}"
    path = "/api/v1/test"
    payload1 = b'{"amount": 100}'
    payload2 = b'{"amount": 200}'

    # First check: returns None
    rec = await IdempotencyManager.get_or_validate(db_session, key, path, payload1)
    assert rec is None

    # Record response
    await IdempotencyManager.record_response(
        db_session, key, path, payload1, 201, {"id": 1, "status": "created"}
    )
    await db_session.commit()

    # Replay with same payload: returns cached record
    replayed = await IdempotencyManager.get_or_validate(db_session, key, path, payload1)
    assert replayed is not None
    assert replayed.response_status == 201
    assert replayed.response_body == {"id": 1, "status": "created"}

    # Replay with different payload: raises 409 ConflictError
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError) as exc_info:
        await IdempotencyManager.get_or_validate(db_session, key, path, payload2)
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"
    assert exc_info.value.status == 409


# ==========================================
# 4. Cursor Pagination Tests
# ==========================================


@pytest.mark.asyncio
async def test_cursor_pagination_forward_traversal(db_session: AsyncSession) -> None:
    service = AuditService(db_session)

    # Insert 15 items
    for i in range(15):
        await service.record_event(
            entity_type="paginate_test",
            entity_id=uuid.uuid4(),
            action=f"action_{i}",
        )
    await db_session.commit()

    # Page 1: limit 5
    page1 = await service.list_events(AuditFilterParams(entity_type="paginate_test", limit=5))
    assert len(page1.items) == 5
    assert page1.has_more is True
    assert page1.next_cursor is not None

    # Page 2: limit 5 using next_cursor
    page2 = await service.list_events(
        AuditFilterParams(entity_type="paginate_test", limit=5, cursor=page1.next_cursor)
    )
    assert len(page2.items) == 5
    assert page2.has_more is True
    assert page2.next_cursor is not None

    # Verify no item overlap between pages
    page1_ids = {item.id for item in page1.items}
    page2_ids = {item.id for item in page2.items}
    assert len(page1_ids.intersection(page2_ids)) == 0
