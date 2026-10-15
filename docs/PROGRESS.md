# Project Progress Tracker

## Project: AI-Powered Municipal Grievance Intelligence and Accountability System

| Milestone | Scope / Deliverables | Status | Completed In |
| :--- | :--- | :--- | :--- |
| **Part 0: Architecture & Specs** | `PROJECT_CONTEXT.md`, `er-diagram.md`, `state-machine.md`, `api-endpoints.md`, `PROGRESS.md` | **DONE** | Session 1 |
| **Part 1: Foundation + Identity** | Project structure for all 12 modules, Docker Compose (Postgres+PostGIS+pgvector, Redis, MinIO), config, db connection, Alembic setup, User/Citizen/Department models, JWT auth, RBAC middleware, seed script, tests. | **DONE** | Session 2 |
| **Part 2: Outbox + Audit + Idempotency** | Transactional Outbox pattern, ARQ worker daemon, Audit logging repository & middleware, Redis-backed Idempotency-Key validation. | **DONE** | Session 3 |
| **Part 3: Complaints + Attachments + Geo** | Complaint submission API, PostGIS spatial queries, MinIO attachment upload & SHA-256 integrity validation, cursor-paginated listing. | **DONE** | Session 3 |
| **Part 4: AI Layer + MockProvider** | Abstract AI provider interface, deterministic MockProvider, Gemini REST driver, versioned prompts, PII redaction, prompt injection defence, circuit breaker, fail-safe degradation to MANUAL_TRIAGE, human review API (accept/override/reject). | **DONE** | Session 4 |
| **Part 5: Routing + Priority + Duplicates** | Geospatial + category routing engine, SLA priority calculator, pgvector cosine similarity + PostGIS distance duplicate incident detection, human override lifecycle. | **DONE** | Session 5 |
| **Part 6: Cases + Activity** | Case creation, single accountable lead department invariant enforcement, internal vs. citizen-visible activity logging, officer assignment workflow. | **DONE** | Session 5 |
| **Part 7: Resolution + Challenges** | Mandatory remediation photo proof verification, 7-day citizen review window, citizen acceptance, dispute/challenge workflow, supervisor uphold/overturn & case reopen. | **DONE** | Session 6 |
| **Part 8: Chaos + Manual Fallback** | AI timeout & failure circuit breaking, low-confidence degradation to manual triage queue, dead-letter event recovery. | **DONE** | Session 6 |
| **Part 9: Evaluation Harness** | Benchmark datasets, evaluation runner for categorization/routing/duplicates, accuracy/precision/recall/F1 metrics computation. | **DONE** | Session 6 |
| **Part 10: Hardening + Docs** | Rate limiting, CORS, upload hardening, secrets scan, RBAC route iteration test, OpenAPI generation, architecture & ADR docs, demo script, Ruff + Mypy validation. | **DONE** | Session 7 |

---

## Current Status Notes
- **Part 1 Complete**:
  - Full modular monolith package layout for all 12 modules (`api`, `service`, `repository`, `schemas`, `models`).
  - Containerization and orchestration: [docker-compose.yml](file:///d:/New%20folder/ai%20synergic/docker-compose.yml), [Dockerfile](file:///d:/New%20folder/ai%20synergic/Dockerfile), [Makefile](file:///d:/New%20folder/ai%20synergic/Makefile), [.env.example](file:///d:/New%20folder/ai%20synergic/.env.example).
  - Strongly typed configuration with `pydantic-settings` in [app/config.py](file:///d:/New%20folder/ai%20synergic/app/config.py).
  - SQLAlchemy 2 async engine & session management in [app/db/session.py](file:///d:/New%20folder/ai%20synergic/app/db/session.py).
  - Alembic configured for async migrations; migration `0001_initial_identity.py` applied for `users`, `citizen_profiles`, `departments`, `department_members`.
  - Identity security: Argon2 password hashing and JWT access & refresh token lifecycle in [app/core/security.py](file:///d:/New%20folder/ai%20synergic/app/core/security.py).
  - RBAC: FastAPI dependency `require_roles(...)` and service-layer role verification in [app/modules/identity/service/identity_service.py](file:///d:/New%20folder/ai%20synergic/app/modules/identity/service/identity_service.py).
  - Observability & Reliability: Structured JSON logging with `request_id_ctx` in [app/core/logging.py](file:///d:/New%20folder/ai%20synergic/app/core/logging.py), `RequestIdMiddleware` for `X-Request-ID` propagation, `/health` and `/ready` probes, and RFC 7807 problem details error handling in [app/core/middleware.py](file:///d:/New%20folder/ai%20synergic/app/core/middleware.py).
  - Seed script in [app/db/seed.py](file:///d:/New%20folder/ai%20synergic/app/db/seed.py) successfully seeding 6 municipal departments and demo accounts for each role (`citizen`, `officer`, `department_lead`, `supervisor`, `admin`, `auditor`).
- **Part 2 Complete (Shared Infrastructure)**:
  - **Transactional Outbox**: `outbox_events` and `dead_letter_events` tables ([app/core/outbox.py](file:///d:/New%20folder/ai%20synergic/app/core/outbox.py)) with `enqueue_outbox_event()` for same-transaction emission; `OutboxProcessor` with exponential backoff retries, max-retry threshold, dead-letter recording, and idempotent execution tracking.
  - **Append-Only Audit Hash Chain**: `audit_events` table ([app/modules/audit/models/audit.py](file:///d:/New%20folder/ai%20synergic/app/modules/audit/models/audit.py)) with cryptographic SHA-256 hash chains (`previous_hash` linking each node to its predecessor), ORM update/delete listeners blocking any in-place mutation, and verification endpoints `GET /api/v1/audit/events` and `GET /api/v1/audit/verify` in [app/modules/audit/api/audit_router.py](file:///d:/New%20folder/ai%20synergic/app/modules/audit/api/audit_router.py).
  - **Idempotency Protection**: `IdempotencyManager` and `extract_idempotency_key` dependency ([app/core/idempotency.py](file:///d:/New%20folder/ai%20synergic/app/core/idempotency.py)) validating raw request body SHA-256 hashes against stored keys; replaying previous response for identical requests with `X-Idempotent-Replay: true` and returning RFC 7807 `409 Conflict` on mismatched payloads.
  - **Reusable Keyset Cursor Pagination**: [app/core/pagination.py](file:///d:/New%20folder/ai%20synergic/app/core/pagination.py) base64 cursor encoding/decoding on `(created_at, id)` with stable forward traversal.
- **Part 3 Complete (Complaints Module)**:
  - **Models & Migration**: `complaints`, `attachments`, and `wards` tables in Alembic migration `0002_shared_and_complaints.py` ([app/modules/complaints/models/complaint.py](file:///d:/New%20folder/ai%20synergic/app/modules/complaints/models/complaint.py)) with spatial bounding coordinates, status indexes, and cascading relationships.
  - **Complaints API**: [app/modules/complaints/api/complaint_router.py](file:///d:/New%20folder/ai%20synergic/app/modules/complaints/api/complaint_router.py) implementing `POST /api/v1/complaints` (citizen, mandatory `Idempotency-Key`), `GET /api/v1/complaints` (citizen sees own; staff sees all with cursor pagination and status/ward filters), `GET /api/v1/complaints/{id}`, and public-safe `GET /api/v1/complaints/{identifier}/tracking` (tracking number or UUID, strictly zero PII).
  - **Ward Lookup**: Point-in-polygon matching via Shapely with bounding box fallback ([app/modules/complaints/service/complaint_service.py](file:///d:/New%20folder/ai%20synergic/app/modules/complaints/service/complaint_service.py)).
  - **Attachment Security**: Validation for MIME types (`image/jpeg`, `image/png`, `image/webp`, `application/pdf`), 15MB file size ceiling, binary magic-byte inspection rejecting executables/scripts, and SHA-256 integrity calculation.
  - **State Transitions & Event Emission**: On submission, status is set to `SUBMITTED`, original user text is preserved verbatim (never overwritten), and both `ComplaintSubmitted` outbox event and audit hash chain entry are committed in the same database transaction.
- **Part 4 Complete (AI Assist & Guardrails)**:
  - **Provider Architecture**: `LLMProvider` and `EmbeddingProvider` abstract interfaces with `GeminiProvider` (async HTTP REST with Gemini 1.5 Flash and text-embedding-004) and deterministic `MockProvider` ([app/modules/ai_assist/service/providers.py](file:///d:/New%20folder/ai%20synergic/app/modules/ai_assist/service/providers.py)) for offline and unit testing.
  - **Versioned Prompts**: Markdown prompt files located under [prompts/v1/](file:///d:/New%20folder/ai%20synergic/prompts/v1) (`language_detect.md`, `interpret.md`, `route.md`, `priority.md`).
  - **Automated Worker Pipeline**: Triggered asynchronously via `ComplaintSubmitted` outbox event; transitions status `AI_TRIAGE_PENDING` -> runs multilingual detection/translation -> parses category, sub-category, location hints, and officer summary -> validates strict separation between `reported_facts` and `inferences` -> asserts root causes are never stated as facts.
  - **Persistent Audit & Tracking**: Stored in `ai_interpretations` table ([app/modules/ai_assist/models/ai_interpretation.py](file:///d:/New%20folder/ai%20synergic/app/modules/ai_assist/models/ai_interpretation.py)) capturing model, prompt version, input hash, raw output, parsed output, confidence, latency ms, and lifecycle status (`PENDING`, `ACCEPTED`, `OVERRIDDEN`, `REJECTED`).
  - **Multi-layered Guardrails**:
    - PII scrubbing regexes redacting Indian phone numbers, emails, and Aadhaar numbers before any provider egress ([app/modules/ai_assist/service/guardrails.py](file:///d:/New%20folder/ai%20synergic/app/modules/ai_assist/service/guardrails.py)).
    - Prompt-injection containment wrapping input in `<untrusted_citizen_submission>` XML boundaries with escaped control tags.
    - System-level circuit breaker (`CircuitBreaker`) tripping to `OPEN` on consecutive provider faults.
    - Pydantic schema validation with single automatic retry on formatting flaws.
  - **Fail-Safe Degradation**: If `AI_ENABLED` kill switch is off, circuit breaker trips, provider times out, or confidence is below threshold (`0.7`), complaint degrades immediately to `MANUAL_TRIAGE` without silent defaults.
  - **Officer Human-in-the-Loop Endpoints**: `GET /api/v1/complaints/{id}/ai-interpretation` and decision routes `POST .../accept`, `POST .../override` (mandates substantive reason of >=5 chars), and `POST .../reject` ([app/modules/ai_assist/api/ai_router.py](file:///d:/New%20folder/ai%20synergic/app/modules/ai_assist/api/ai_router.py)) recording deciding officer ID, timestamp, and immutable audit event.
- **Part 5 Complete (Routing + Priority + Duplicates - Recommendations Only)**:
  - **Routing Engine**:
    - Admin-configurable, versioned `routing_rules` ([app/modules/routing/models/routing.py](file:///d:/New%20folder/ai%20synergic/app/modules/routing/models/routing.py)) supporting category, optional ward/geo-zone, priority override, and `effective_from`/`effective_to` windowing.
    - Endpoints `POST /api/v1/routing/rules`, `GET /api/v1/routing/rules`, and `PUT /api/v1/routing/rules/{id}` ([app/modules/routing/api/routing_router.py](file:///d:/New%20folder/ai%20synergic/app/modules/routing/api/routing_router.py)).
    - Recommendation generator producing top-3 ranked departments with confidence and reasons, rule version tracking, and officer decision lifecycle (`accept`, `override` with mandatory reason >=5 chars, `reject`).
    - Enforced invariant: complaint moves to `ROUTED` only after human officer decision.
  - **Priority Policies & Safety Invariant**:
    - Configurable `priority_policies` ([app/modules/priority/models/priority.py](file:///d:/New%20folder/ai%20synergic/app/modules/priority/models/priority.py)) with multilingual keyword detection across English, Hindi (Devanagari), and Kannada.
    - **CRITICAL INVARIANT (enforced in code)**: Safety rule hits can ONLY raise the suggested priority, NEVER lower it (`enforce_safety_only_raises`).
    - Stored in `priority_assessments` with explicit rule hits, model reasoning, final suggested band, suggested SLA hours, and human decision.
    - Dedicated safety-critical priority queue endpoint: `GET /api/v1/priority/queue`.
  - **Duplicate Detection & Citizen Support**:
    - Vector embeddings stored in `complaint_embeddings` generated via `EmbeddingProvider` (pgvector-ready).
    - Multi-factor candidate search combining Haversine spatial radius + embedding cosine similarity + category overlap + temporal decay window.
    - Ranked candidates stored in `duplicate_candidates` with granular similarity breakdown.
    - Officer endpoints `POST /api/v1/complaints/{id}/duplicates/{candidate_id}/link` and `/dismiss`.
    - **CRITICAL INVARIANT**: NEVER auto-merge; linked complaints maintain distinct records.
    - Citizen-facing `GET /api/v1/complaints/nearby-similar` returning strictly non-sensitive fields (zero PII) and `POST /api/v1/complaints/{id}/support` enabling citizen endorsement ("this is the same issue").
  - Alembic migration `0004_routing_priority_duplicates.py`.
- **Part 6 Complete (Cases + Activity + Central State Machine)**:
  - **Cases & Single Lead Invariant**:
    - `cases`, `case_complaints`, `case_departments`, and `case_reassign_requests` models ([app/modules/cases/models/case.py](file:///d:/New%20folder/ai%20synergic/app/modules/cases/models/case.py)).
    - Grouping one or more citizen complaints under a single unified case.
    - **Single Accountable Lead Invariant**: Enforced both in service layer and via DB partial unique index on `case_departments` (`is_lead = TRUE`).
    - Jurisdictional transfer workflow via `CaseReassignRequest` with mandatory reasons.
  - **Central State Machine Module**:
    - Central transition authority in [app/modules/cases/service/state_machine.py](file:///d:/New%20folder/ai%20synergic/app/modules/cases/service/state_machine.py).
    - Single source of truth defining allowed transitions, required roles, and required inputs from `TRIAGE_REVIEW` through `IN_PROGRESS`, plus `REJECTED_WITH_REASON` and `REASSIGN_REQUESTED`.
    - Returns RFC 7807 problem details error (`ILLEGAL_TRANSITION`, `ROLE_NOT_PERMITTED`, `INVALID_TRANSITION_INPUT`) for any illegal transition or unauthorized actor.
    - **Universal Side-Effect Contract**: Every transition commits in the SAME transaction: case/complaint status update, immutable audit hash chain event, immutable case activity log, and transactional outbox event.
  - **Official Case Activity & Immutability**:
    - `case_activities` and `citizen_updates` models ([app/modules/activity/models/activity.py](file:///d:/New%20folder/ai%20synergic/app/modules/activity/models/activity.py)).
    - Append-only immutability enforced at ORM and DB trigger levels (blocking any UPDATE or DELETE).
    - Visibility segregation: `INTERNAL` vs. `CITIZEN_VISIBLE`.
    - Staff endpoint `GET /api/v1/cases/{id}/activities` returns complete history.
    - Citizen endpoint `GET /api/v1/cases/citizen-timeline/{complaint_id}`: Strictly filters to `CITIZEN_VISIBLE` entries for the citizen's own complaints only; completely blocks confidential `INTERNAL` entries and other citizens' timelines.
  - Alembic migration `0005_cases_and_activity.py`.
- **Part 7 Complete (Resolution, Citizen Challenges & Reviews)**:
  - **Resolution Proposals**:
    - `resolution_proposals` table ([app/modules/challenges/models/challenge.py](file:///d:/New%20folder/ai%20synergic/app/modules/challenges/models/challenge.py)) capturing verified remediation proof, root cause notes, and officer verification timestamp.
    - Strict invariant: transition to `RESOLUTION_PROPOSED` and `CITIZEN_REVIEW` requires $\ge 1$ verified evidence attachment, summary notes, and human officer sign-off.
    - System NEVER marks a case resolved by itself without human evidence sign-off.
  - **Closure Rules**:
    - Case can reach `CLOSED` state **only** if remediation evidence is verified AND (citizen explicitly confirms satisfaction OR 7-day review window expires with no challenge OR challenge dispute is formally reviewed).
    - Closure without evidence is rejected with RFC 7807 problem details `EVIDENCE_REQUIRED`.
    - Automated worker job `process_expired_review_windows()` (`POST /api/v1/cases/worker/expire-review-windows`) closes cases whose review window has elapsed without active dispute.
  - **Citizen Disputes & Challenges**:
    - `citizen_challenges` table supporting disputes against official action, rejection, proposed resolution, or priority decision.
    - Citizen endpoints: `POST /api/v1/cases/{id}/confirm`, `POST /api/v1/cases/{id}/challenge`, `GET /api/v1/cases/{id}/challenge`.
    - Automatic SLA timers (48h) with background worker job `process_challenge_sla_breaches()` (`POST /api/v1/challenges/worker/sla-escalations`) automatically escalating overdue disputes to the supervisor queue and logging case activities.
  - **Independent Challenge Reviews & Anti-Self-Review**:
    - `challenge_reviews` and `reopen_events` tables.
    - **CRITICAL ANTI-SELF-REVIEW INVARIANT**: The reviewer MUST be different from the original actor and NOT in the original actor's chain of action (checked against case creator, assigned officer, proposing officer, activity actors, and citizen; returns `403 Forbidden` with `SELF_REVIEW_BLOCKED`).
    - Outcomes: `UPHELD` (original resolution stands -> case closed) or `OVERTURNED` (dispute validated -> creates immutable `ReopenEvent` and reopens case `REOPENED` -> `IN_PROGRESS`).
    - Staff queue: `GET /api/v1/challenges/queue` and review decision `POST /api/v1/challenges/{id}/review`.
  - **Full Audit Trail & Citizen Timeline**:
    - Every action is atomically hashed into `audit_events`, logged to `case_activities` with designated visibility, and enqueued in `outbox_events`.
    - Citizens viewing `/api/v1/cases/citizen-timeline/{complaint_id}` see verified proposals, challenge filings, reopenings, and closures in real-time while internal supervisor reviews remain protected.
  - Alembic migration `0006_resolutions_and_challenges.py`.
- **Part 8 Complete (Chaos Engineering, Manual Triage Fallback & Notifications)**:
  - **Manual Triage Workflow**:
    - Dedicated `MANUAL_TRIAGE` queue endpoint `GET /api/v1/triage/manual/queue` for complaints degraded from AI downtime, circuit breaking, low confidence (<0.7), or garbage payloads.
    - Officer submission endpoint `POST /api/v1/triage/manual/{complaint_id}` ([app/modules/ai_assist/api/triage_router.py](file:///d:/New%20folder/ai%20synergic/app/modules/ai_assist/api/triage_router.py)) to manually assign category, routing department, and priority with substantive rationale without requiring AI.
    - Produces the identical downstream records as the AI pipeline:
      - `AIInterpretation` with `model="manual-officer-triage"`, `confidence=1.0`, `recommendation_status="ACCEPTED"`, and metadata marked `source="MANUAL"`.
      - `RoutingRecommendation` with target department marked `source="MANUAL"`.
      - `PriorityAssessment` with priority band, SLA hours, and rule hit marked `source="MANUAL"`.
      - Creates or updates `Case` in `ROUTED` status with accountable lead department and assigned priority.
      - Commits atomic `audit_events`, `case_activities`, and `outbox_events` all marked `source="MANUAL"`.
  - **Admin-Only Chaos Simulation Core**:
    - [app/core/chaos.py](file:///d:/New%20folder/ai%20synergic/app/core/chaos.py) and router [app/modules/admin/api/chaos_router.py](file:///d:/New%20folder/ai%20synergic/app/modules/admin/api/chaos_router.py) exposing `/api/v1/admin/chaos`.
    - **Production Safety Guarantee**: Invariant strictly enforced rejecting execution with `403 Forbidden` (`CHAOS_FORBIDDEN_IN_PRODUCTION`) whenever `ENV=production`.
    - Simulation knobs:
      - `disable_ai`: Simulates complete AI provider outage $\to$ immediate degradation to `MANUAL_TRIAGE`.
      - `ai_garbage`: Simulates corrupted/malformed token output $\to$ retries exhaust $\to$ graceful fallback to `MANUAL_TRIAGE`.
      - `delay_worker_ms` & `stop_worker`: Pauses or delays outbox processor execution.
      - `fail_notifications`: Injects channel faults into delivery channels.
      - `db_error_operations`: Injects clean database exceptions into named operations (e.g. `case.transition`) triggering clean transaction rollbacks.
    - Real-time simulation state banner endpoint `GET /api/v1/admin/chaos`.
  - **Pluggable Notifications Module**:
    - Pluggable channel architecture (`NotificationChannel`, `ConsoleNotificationChannel`) in [app/modules/notifications/service/channels.py](file:///d:/New%20folder/ai%20synergic/app/modules/notifications/service/channels.py).
    - `NotificationService` ([app/modules/notifications/service/notification_service.py](file:///d:/New%20folder/ai%20synergic/app/modules/notifications/service/notification_service.py)) with retry loop (3 attempts) and automatic dead-lettering to `dead_letter_events`.
    - **CRITICAL INVARIANT**: Case state, complaints, and audit records are completely decoupled and **never affected** by notification delivery failures.
    - Alembic migration `0007_notifications_and_chaos.py` for `notification_logs`.
- **Part 9 Complete (Evaluation Harness & Benchmark Metrics)**:
  - **Synthetic Benchmark Dataset**:
    - 215 ground-truth municipal complaints in `data/eval/dataset_v1.jsonl` with full schema specification in [data/eval/SCHEMA.md](file:///d:/New%20folder/ai%20synergic/data/eval/SCHEMA.md).
    - Diverse multilingual split: English (70), Hindi (59), Kannada (53), and Code-Mixed English-Hindi/Kannada (33).
    - Safety-critical ground truths: 50 high-hazard samples (target was ≥40) covering live wires, gas leaks, open manholes, sewer backflows, and wall collapses.
    - Duplicate detection clusters: 10 duplicate incident groups encompassing 30 co-occurring complaints.
    - Stress-testing edge cases: 15 vague complaints (unclear, single-word, un-actionable) and 15 adversarial/prompt-injection samples (jailbreak attempts, system prompt overrides, delimiter attacks).
  - **Evaluation Engine & Metrics Pipeline**:
    - [app/modules/evaluation/service/evaluator.py](file:///d:/New%20folder/ai%20synergic/app/modules/evaluation/service/evaluator.py) runs the actual production pipeline components:
      - **Language Detection Accuracy**: 99.5% accuracy across EN, HI, KN, and code-mixed inputs.
      - **Category Accuracy & Routing Accuracy**: Measures Top-1 (70.2%) and Top-3 (77.2%) department matching against municipal ground truths.
      - **Safety-Critical Recall**: 100.0% recall with explicit itemized listing of every false negative (0 false negatives with mock provider).
      - **Priority Band Agreement**: Evaluates model and rule suggestions against expected priority bands.
      - **Duplicate Precision & Recall@k**: 63.3% precision and recall@3 evaluating embedding similarity.
      - **Abstention Rate**: 11.6% correctly abstaining and routing vague/adversarial complaints to `MANUAL_TRIAGE`.
      - **Confidence Calibration**: Binned calibration into 5 discrete confidence ranges comparing mean confidence against actual accuracy with calibration error calculation.
      - **Latency Percentiles**: Precise tracking of p50 (median), p90, p95, and p99 pipeline latencies in milliseconds.
  - **Report Generation & Provider Comparison**:
    - CLI runner `app/modules/evaluation/cli.py` and `make eval` target generating timestamped reports in `reports/eval_<timestamp>.json` and `reports/eval_<timestamp>.md`.
    - Supports `--provider mock|gemini` and `--compare` flag generating side-by-side comparative tables evaluating both Mock and Gemini providers in a unified report.
  - **Database Persistence & Admin/Auditor Endpoints**:
    - Alembic migration `0008_evaluation_module.py` creates `eval_datasets`, `eval_runs`, and `eval_results` tables with JSON metric payloads, confusion matrices, and audit logs.
    - Repositories and models in [app/modules/evaluation/models/evaluation.py](file:///d:/New%20folder/ai%20synergic/app/modules/evaluation/models/evaluation.py) and [app/modules/evaluation/repository/evaluation_repository.py](file:///d:/New%20folder/ai%20synergic/app/modules/evaluation/repository/evaluation_repository.py).
    - REST endpoints in [app/modules/evaluation/api/evaluation_router.py](file:///d:/New%20folder/ai%20synergic/app/modules/evaluation/api/evaluation_router.py): `GET /api/v1/eval/runs` and `GET /api/v1/eval/runs/{id}` protected by `require_roles(UserRole.ADMIN, UserRole.AUDITOR)`.
  - **CI-Style Threshold Enforcement**:
    - Fails the evaluation command with exit code 1 if safety-critical recall drops below a configurable minimum (`--min-safety-recall`, default `0.95`).
- **Part 10 Complete (Hardening, Verification & Documentation)**:
  - **Security & Rate Limiting**:
    - Redis-backed sliding-window rate limiting middleware ([app/core/rate_limit.py](file:///d:/New%20folder/ai%20synergic/app/core/rate_limit.py)) configured with granular tiers: login (10/min), register (5/min), refresh (20/min), attachments upload (15/min), chaos/admin (10/min), and default (60/min per IP).
    - Graceful degradation: in local/test environments lacking a live Redis instance, the limiter automatically warns and falls back to allow-all to ensure testing workflows are unhindered.
    - CORS middleware configured in [app/main.py](file:///d:/New%20folder/ai%20synergic/app/main.py) with strictly validated origin lists (rejects wildcard `*` and untrusted reflections).
  - **Upload Hardening & Secrets Audit**:
    - Multilayer file upload security verifying MIME whitelist (`image/jpeg`, `image/png`, `image/webp`, `application/pdf`), 15MB file size limit, and binary magic-byte inspection rejecting executables/ELF binaries disguised as images.
    - Zero secrets in repository: automated source scanner asserting no hardcoded API keys, tokens, or private certificates across the codebase.
  - **RBAC & Authorization Route Iteration**:
    - Automated test iterating all 62+ registered API routes:
      - Protected routes reject unauthenticated requests with `401 Unauthorized`.
      - Staff-only routes reject citizen credentials with `403 Forbidden`.
      - Admin-only routes reject officer credentials with `403 Forbidden`.
    - Every API endpoint is equipped with descriptive summaries and OpenAPI response models.
  - **OpenAPI & Architectural Documentation**:
    - Complete, live-generated OpenAPI 3.1 specification committed to [docs/openapi.json](file:///d:/New%20folder/ai%20synergic/docs/openapi.json) with schemas and parameter definitions for all routes.
    - [docs/architecture.md](file:///d:/New%20folder/ai%20synergic/docs/architecture.md) featuring Mermaid diagrams for modular monolith structure, outbox async pipeline, state machine transitions, and data flow.
    - 6 Architecture Decision Records in `docs/adr/`:
      - `001-modular-monolith.md` (Modular Monolith over Microservices)
      - `002-transactional-outbox.md` (Transactional Outbox Pattern for Async Reliability)
      - `003-pgvector-duplicate-detection.md` (PostGIS + pgvector for Spatial & Semantic Deduplication)
      - `004-hash-chain-audit.md` (Append-Only SHA-256 Hash Chain for Tamper-Evident Auditing)
      - `005-provider-abstraction.md` (AI Provider Abstraction with Circuit Breaking & Graceful Fallback)
      - `006-state-machine.md` (Centralized Case State Machine with Side-Effect Commit Contract)
  - **README & 10-Minute Demo Script**:
    - Comprehensive [README.md](file:///d:/New%20folder/ai%20synergic/README.md) containing setup instructions, environment config, architectural summary, and an executable 10-minute demo script covering:
      1. Citizen grievance submission with photo attachment.
      2. Asynchronous AI triage & language identification.
      3. Human officer routing review & acceptance.
      4. Single accountable lead department assignment & progress tracking.
      5. Resolution proposal with mandatory remediation photo proof.
      6. Citizen review window & formal challenge/dispute filing.
      7. Independent supervisor review with anti-self-review enforcement & case reopening.
      8. Chaos simulation (`POST /api/v1/admin/chaos`) demonstrating graceful fallback to `MANUAL_TRIAGE`.
      9. Model evaluation harness execution (`make eval`).
  - **Code Quality & Test Verification**:
    - **83/83 tests passing** (100% pass rate in `pytest -v`) covering unit, integration, RBAC, and security hardening tests.
    - **100% Ruff lint and formatting compliance** (0 errors).
    - **100% Mypy type-checking pass** (`Success: no issues found in 161 source files`).
  - **Remaining Known Gaps (Transparent Disclosure)**:
    - *Full Spatial/Vector Functionality*: Requires Docker Compose containers running PostgreSQL 16 with PostGIS and pgvector extensions; in pure SQLite unit tests, spatial lookups use bounding-box fallbacks and vector searches use pure-Python cosine similarity.
    - *Live Redis vs In-Memory Fallback*: Distributed rate limiting and ARQ background job daemon rely on live Redis (`REDIS_URL`). When Redis is unreachable, the rate limiter falls back to allow-all and unit tests run the outbox processor synchronously.
    - *Live Gemini LLM Egress*: Production operations require a valid `GEMINI_API_KEY` for live generative responses and embeddings; deterministic `MockProvider` is used for test runs and offline evaluations.
    - *Frontend UI*: The system provides a complete REST backend API with OpenAPI specifications and demo curl scripts; a web/mobile UI client is designed to consume these contracts as future work.

