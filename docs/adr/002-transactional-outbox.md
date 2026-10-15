# ADR-002: Transactional Outbox Pattern

## Status
**Accepted** — Session 2

## Context
The system requires that domain events (e.g., `ComplaintSubmitted`, `case.routed`) trigger asynchronous side effects (AI triage, notifications) reliably. The dual-write problem — writing to both a database and a message queue in separate transactions — risks data loss or ghost events if either write fails.

## Decision
Implement the **Transactional Outbox** pattern:

1. Every mutation writes both the state change AND the domain event to the `outbox_events` table **within the same PostgreSQL transaction**.
2. An ARQ async worker polls the `outbox_events` table, processes events, and marks them as dispatched.
3. Events that exceed `max_retries` (default: 5) with exponential backoff are moved to `dead_letter_events` for manual inspection.
4. Each event carries an `idempotency_key` to prevent duplicate processing.

### Key tables:
- `outbox_events`: `id`, `event_type`, `aggregate_type`, `aggregate_id`, `payload`, `status`, `retries`, `created_at`, `processed_at`
- `dead_letter_events`: Mirror of outbox with `failure_reason` and `moved_at`

### Implementation:
- `enqueue_outbox_event()` in `app/core/outbox.py` — called inside service transactions.
- `OutboxProcessor` — ARQ worker polling with configurable batch size and backoff.

## Consequences

### Positive
- **Atomicity guaranteed**: Either both state change and event persist, or neither does.
- **At-least-once delivery**: Worker retries with exponential backoff ensure delivery.
- **Dead-letter visibility**: Failed events are preserved for debugging, not silently lost.
- **No external message broker dependency**: Uses PostgreSQL as the event store.

### Negative
- Polling introduces latency (configurable, default 1s) vs. push-based messaging.
- Dead-letter events require manual intervention or a recovery workflow.
- Outbox table grows unbounded without periodic cleanup (mitigated by TTL pruning).

### Alternatives Considered
- **Direct Redis pub/sub**: Rejected — no atomicity with DB writes.
- **PostgreSQL LISTEN/NOTIFY**: Considered but rejected — doesn't survive process restarts and has payload size limits.
- **External broker (RabbitMQ/Kafka)**: Rejected — premature operational complexity for MVP.
