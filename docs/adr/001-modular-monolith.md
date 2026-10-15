# ADR-001: Modular Monolith Architecture

## Status
**Accepted** — Session 1

## Context
We needed an architecture that balances the development velocity of a single deployable with the organizational clarity of domain-driven boundaries. A full microservices decomposition was premature for a system with 12 tightly-coupled domain modules sharing a single PostgreSQL database, one development team, and no independent scaling requirements at MVP.

## Decision
Adopt a **modular monolith** with strict module boundaries:

```
app/modules/<module_name>/
├── api/           # Thin FastAPI routers (I/O validation only)
├── service/       # All business logic
├── repository/    # Database queries (SQLAlchemy)
├── schemas/       # Pydantic request/response models
└── models/        # SQLAlchemy ORM entities
```

### Rules enforced:
1. **No cross-module model imports** — modules communicate through service interfaces or transactional outbox domain events.
2. **Routers are thin** — they validate I/O via Pydantic and delegate to services; no business logic in routers.
3. **Each module owns its tables** — Alembic migrations are module-scoped.
4. **All 12 modules** live in a single deployment unit: `identity`, `complaints`, `ai_assist`, `routing`, `priority`, `duplicates`, `cases`, `activity`, `challenges`, `audit`, `notifications`, `evaluation`.

## Consequences

### Positive
- Single deployment, single CI pipeline, single database — drastically simpler ops.
- Module boundaries enforce separation of concerns without network overhead.
- Easy to refactor to microservices later by extracting modules to separate services.
- Shared transaction context enables atomic multi-table operations (critical for audit + outbox).

### Negative
- All modules must share the same Python process and deployment schedule.
- A bug in any module can theoretically crash the entire application.
- Requires discipline to maintain module boundaries (no enforcement beyond code review).

### Risks
- If the team grows beyond 3–4 engineers, module boundaries may erode. Mitigated by lint rules, CI checks, and ADR documentation.
