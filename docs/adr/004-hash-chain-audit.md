# ADR-004: SHA-256 Hash-Chain Audit Trail

## Status
**Accepted** — Session 2

## Context
Municipal grievance systems handle public trust. Every action — routing decisions, priority overrides, resolution proposals, challenge reviews — must be immutable and tamper-evident. Standard database audit tables can be silently modified by anyone with DBA access.

## Decision
Implement a **cryptographic hash chain** on the `audit_events` table:

1. **Each audit event** stores its own SHA-256 hash computed over: `event_type + entity_type + entity_id + actor_id + old_state + new_state + timestamp + previous_hash`.
2. **Chain integrity**: Each event's `previous_hash` field links to the hash of the preceding event, forming a blockchain-like chain.
3. **Immutability enforcement**:
   - SQLAlchemy ORM event listeners **block** any `UPDATE` or `DELETE` on `audit_events` at the Python layer.
   - Database trigger (in migration) blocks `UPDATE`/`DELETE` at the PostgreSQL layer.
4. **Verification endpoint**: `GET /api/v1/audit/verify` walks the entire chain and reports integrity status, broken links, and total events verified.

### Schema:
```python
class AuditEvent:
    id: UUID
    entity_type: str  # "complaint", "case", "challenge"
    entity_id: UUID
    action: str  # "case.routed", "challenge.upheld"
    actor_id: UUID
    actor_role: str
    old_state: JSON
    new_state: JSON
    event_hash: str  # SHA-256 of this event
    previous_hash: str  # SHA-256 of preceding event
    created_at: datetime
```

## Consequences

### Positive
- **Tamper evidence**: Any modification to historical records breaks the hash chain, detectable by the verification endpoint.
- **Regulatory compliance**: Suitable for audit and Right to Information (RTI) requirements.
- **Zero external dependencies**: Uses PostgreSQL and Python's `hashlib` — no blockchain infrastructure needed.
- **Append-only**: ORM + DB triggers prevent both accidental and malicious mutations.

### Negative
- **Full-chain verification is O(n)**: For very large chains (>1M events), verification may need pagination or sampling.
- **No non-repudiation**: Without PKI, the hash chain proves integrity but not that a specific human performed the action.
- **Schema evolution risk**: Changing the hash computation algorithm requires a chain migration strategy.

### Alternatives Considered
- **Database triggers only**: Insufficient — triggers can be disabled by superusers.
- **External append-only log (Kafka)**: Operationally complex and doesn't prevent DB mutation.
- **Blockchain**: Massively over-engineered for a single-org municipal system.
