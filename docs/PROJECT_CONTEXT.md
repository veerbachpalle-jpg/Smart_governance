# AI-Powered Municipal Grievance Intelligence & Accountability System

## 1. System Goal
Transform municipal grievance handling by augmenting human decision-makers: accurately understanding citizen complaints, evaluating severity/priority, recommending routing to municipal departments, detecting duplicate incidents across geography and time, and tracking cases through evidence-backed resolution with citizen accountability.

## 2. HARD MVP Boundary (Enforced in Code)
- **AI Recommends & Assists Only**: The system NEVER autonomously decides routing, sets final priority, merges duplicates, or closes cases.
- **No Unverified Root Causes**: AI-suggested categories or causes remain unconfirmed suggestions until validated by municipal personnel.
- **Evidence-Backed Physical Closure**: No complaint/case can transition to resolved/closed without:
  1. Mandatory photographic/documentary evidence of remediation attached.
  2. Human officer verification and explicit sign-off.
- **Recommendation Lifecycle**: Every AI output is recorded in dedicated tables with status `PENDING`, `ACCEPTED`, `OVERRIDDEN`, or `REJECTED`, timestamped, and linked to the deciding human actor ID (`decided_by`).
- **Fail-Safe Degradation**: If an AI service fails, times out, or scores below confidence threshold, the complaint automatically falls back to standard manual officer triage.

## 3. Technology Stack
- **Runtime & Framework**: Python 3.12, FastAPI, Pydantic v2
- **Persistence & ORM**: SQLAlchemy 2 (asyncio), PostgreSQL 16 + PostGIS (geospatial) + pgvector (embedding search), Alembic migrations
- **Workers & Messaging**: Redis 7 + ARQ async worker, Transactional Outbox pattern
- **Object Storage**: MinIO (S3-compatible) for citizen & resolution media attachments
- **Security & Auth**: Stateless JWT (access + refresh), bcrypt password hashing, RBAC
- **DevOps & Tooling**: Docker Compose, pytest (asyncio), ruff (linter/formatter), mypy (strict typing)

## 4. Architecture Rules
- **Modular Monolith**: Core modules partitioned under `app/modules/<module_name>`:
  `identity`, `complaints`, `ai_assist`, `routing`, `priority`, `duplicates`, `cases`, `activity`, `challenges`, `audit`, `notifications`, `evaluation`.
- **Module Structure**: Every module contains `api/` (thin routers), `service/` (all business logic), `repository/` (DB queries), `schemas/` (Pydantic models), `models/` (SQLAlchemy entities).
- **Separation of Concerns**: Routers validate I/O and forward to services. Cross-module calls go through explicit service contracts or outbox domain events.
- **Transactional Outbox**: Mutation and domain events commit atomically in the same PostgreSQL transaction. ARQ workers poll/consume outbox records.
- **Idempotency**: All mutation POST/PUT operations accept an `Idempotency-Key` header stored in Redis/DB with 24h TTL.
- **Pagination**: Keyset/cursor-based pagination on all listing endpoints (`limit`, `cursor`).
- **API Versioning**: All public endpoints exposed under `/api/v1`.

## 5. Roles & Access Control
- `citizen`: Submit complaints, view own complaints/activity, provide updates, accept/challenge resolution.
- `officer`: Review triage recommendations, update case progress, upload remediation proof, propose resolution.
- `department_lead`: Accept routed cases for department, assign officers, request reassignment, approve proposals.
- `supervisor`: Override routing/priority, reassign cases across departments, review citizen challenges, handle escalations.
- `admin`: Manage users, departments, versioned routing rules, priority matrices, system configs.
- `auditor`: Read-only access to all complaints, cases, activity logs, AI recommendations, and audit trails.

## 6. Case State Machine Summary
`SUBMITTED` -> `AI_TRIAGE_PENDING` -> `TRIAGE_REVIEW` -> `ROUTED` -> `ACCEPTED_BY_LEAD` -> `IN_PROGRESS` -> `RESOLUTION_PROPOSED` -> `CITIZEN_REVIEW` -> `CLOSED`.
- **Side Paths**:
  - `REJECTED_WITH_REASON` (from triage/review if out of municipal scope/spam).
  - `REASSIGN_REQUESTED` (dept lead requests rerouting -> back to `ROUTED`).
  - `CHALLENGED` (citizen contests resolution within time window) -> `UNDER_REVIEW` -> `UPHELD` (reopens case -> `REOPENED` -> `IN_PROGRESS`) OR `OVERTURNED` (challenge denied -> `CLOSED`).
- **Closure Guarantee**: Closure requires verified evidence AND (citizen confirmation OR 7-day review window expiry without challenge). Every transition writes immutable records to `audit_events` and `case_activities`.

## 7. Coding & Engineering Conventions
- **Typing**: Strict `mypy` compliance. Explicit return types and argument types on all functions. No untyped `dict` payloads across service boundaries.
- **Error Standard**: RFC 7807 problem details (`{ "type": str, "title": str, "status": int, "detail": str, "instance": str, "code": str, "errors": list }`).
- **Naming**: `snake_case` for variables, functions, and DB tables/columns; `PascalCase` for classes/schemas; `SCREAMING_SNAKE_CASE` for enum values.
- **Tests**: Organized under `tests/` mirroring modules (`tests/unit/`, `tests/integration/`, `tests/e2e/`), using `pytest-asyncio` with isolated DB transactions.

