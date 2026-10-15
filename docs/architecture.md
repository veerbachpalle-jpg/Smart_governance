# System Architecture

## Overview

The Municipal Grievance Intelligence & Accountability System is a **modular monolith** built with Python 3.12, FastAPI, SQLAlchemy 2 (async), and PostgreSQL. It augments human decision-makers with AI-powered triage while enforcing strict evidence-based accountability through an immutable audit trail.

---

## High-Level Architecture Diagram

```mermaid
graph TB
    subgraph "Client Layer"
        CIT["Citizen App / Portal"]
        OFF["Officer Console"]
        ADM["Admin Dashboard"]
    end

    subgraph "API Gateway"
        CORS["CORS Middleware"]
        RL["Rate Limiter (Redis)"]
        RID["Request-ID Middleware"]
        AUTH["JWT Auth + RBAC"]
    end

    subgraph "FastAPI Application"
        direction TB
        subgraph "API Routers (Thin Layer)"
            R_AUTH["/auth"]
            R_COMP["/complaints"]
            R_AI["/ai-assist"]
            R_ROUTE["/routing"]
            R_PRIO["/priority"]
            R_DUP["/duplicates"]
            R_CASE["/cases"]
            R_ACT["/activities"]
            R_CHALL["/challenges"]
            R_AUDIT["/audit"]
            R_EVAL["/eval"]
            R_CHAOS["/admin/chaos"]
            R_TRIAGE["/triage/manual"]
        end

        subgraph "Service Layer (Business Logic)"
            SVC_ID["IdentityService"]
            SVC_COMP["ComplaintService"]
            SVC_AI["AIAssistService"]
            SVC_ROUTE["RoutingService"]
            SVC_PRIO["PriorityService"]
            SVC_DUP["DuplicateService"]
            SVC_CASE["CaseService"]
            SVC_SM["CaseStateMachine"]
            SVC_ACT["ActivityService"]
            SVC_CHALL["ChallengeService"]
            SVC_AUDIT["AuditService"]
            SVC_NOTIF["NotificationService"]
            SVC_EVAL["EvaluationRunner"]
        end

        subgraph "Repository Layer (Data Access)"
            REPO["Module Repositories"]
        end
    end

    subgraph "AI Provider Abstraction"
        MOCK["MockProvider (Deterministic)"]
        GEMINI["GeminiProvider (REST)"]
        GUARD["Guardrails (PII, Injection, Circuit Breaker)"]
    end

    subgraph "Data & Infrastructure"
        PG["PostgreSQL 16 + PostGIS + pgvector"]
        REDIS["Redis 7"]
        MINIO["MinIO (S3-compatible)"]
        OUTBOX["Transactional Outbox"]
        ARQ["ARQ Async Workers"]
    end

    CIT --> CORS
    OFF --> CORS
    ADM --> CORS
    CORS --> RL --> RID --> AUTH

    AUTH --> R_AUTH & R_COMP & R_AI & R_ROUTE & R_PRIO & R_DUP & R_CASE & R_ACT & R_CHALL & R_AUDIT & R_EVAL & R_CHAOS & R_TRIAGE

    R_AUTH --> SVC_ID
    R_COMP --> SVC_COMP
    R_AI --> SVC_AI
    R_ROUTE --> SVC_ROUTE
    R_PRIO --> SVC_PRIO
    R_DUP --> SVC_DUP
    R_CASE --> SVC_CASE
    SVC_CASE --> SVC_SM
    R_ACT --> SVC_ACT
    R_CHALL --> SVC_CHALL
    R_AUDIT --> SVC_AUDIT

    SVC_AI --> GUARD --> MOCK & GEMINI

    SVC_ID & SVC_COMP & SVC_CASE & SVC_CHALL --> REPO
    REPO --> PG
    SVC_DUP --> PG

    SVC_SM --> OUTBOX
    OUTBOX --> ARQ
    ARQ --> SVC_NOTIF

    SVC_COMP --> MINIO
    REDIS --- RL
    REDIS --- ARQ
    REDIS --- OUTBOX
```

---

## Module Decomposition

```mermaid
graph LR
    subgraph "Modular Monolith – app/modules/"
        identity["identity<br/>Users, Auth, RBAC"]
        complaints["complaints<br/>Submissions, Attachments, Geo"]
        ai_assist["ai_assist<br/>AI Triage, Guardrails, Providers"]
        routing["routing<br/>Rules, Recommendations"]
        priority["priority<br/>Policies, Safety Invariants"]
        duplicates["duplicates<br/>pgvector, Spatial, Candidates"]
        cases["cases<br/>Lifecycle, State Machine"]
        activity["activity<br/>Immutable Logs, Timeline"]
        challenges["challenges<br/>Resolutions, Disputes, Reviews"]
        audit["audit<br/>Hash Chain, Verification"]
        notifications["notifications<br/>Pluggable Channels"]
        evaluation["evaluation<br/>Benchmarks, Metrics"]
    end

    identity --> complaints
    complaints --> ai_assist
    ai_assist --> routing & priority & duplicates
    routing & priority --> cases
    cases --> activity & challenges
    challenges --> audit
    cases --> audit
    audit -.-> notifications
```

---

## Case State Machine

```mermaid
stateDiagram-v2
    [*] --> SUBMITTED : Citizen submits complaint

    SUBMITTED --> AI_TRIAGE_PENDING : Outbox enqueues AI task
    SUBMITTED --> REJECTED_WITH_REASON : Officer early rejection

    AI_TRIAGE_PENDING --> TRIAGE_REVIEW : AI completes OR degrades
    AI_TRIAGE_PENDING --> MANUAL_TRIAGE : AI fails / low confidence

    MANUAL_TRIAGE --> TRIAGE_REVIEW : Officer manual assessment

    TRIAGE_REVIEW --> ROUTED : Officer accepts triage + routing
    TRIAGE_REVIEW --> REJECTED_WITH_REASON : Officer rejects

    ROUTED --> ACCEPTED_BY_LEAD : Dept Lead accepts
    ROUTED --> REJECTED_WITH_REASON : Supervisor rejects
    ROUTED --> CHALLENGED : Citizen challenges routing

    ACCEPTED_BY_LEAD --> IN_PROGRESS : Officer assigned
    ACCEPTED_BY_LEAD --> REASSIGN_REQUESTED : Lead declines

    IN_PROGRESS --> REASSIGN_REQUESTED : Misrouting identified
    REASSIGN_REQUESTED --> ROUTED : Supervisor reassigns

    IN_PROGRESS --> RESOLUTION_PROPOSED : Evidence attached
    IN_PROGRESS --> CHALLENGED : Citizen challenges action

    RESOLUTION_PROPOSED --> CITIZEN_REVIEW : Review window opens

    CITIZEN_REVIEW --> CLOSED : Citizen confirms / window expires
    CITIZEN_REVIEW --> CHALLENGED : Citizen disputes

    CHALLENGED --> UNDER_REVIEW : Supervisor opens review
    CHALLENGED --> UPHELD : Direct uphold
    CHALLENGED --> OVERTURNED : Direct overturn
    CHALLENGED --> REOPENED : Direct reopen
    CHALLENGED --> CLOSED : Challenge dismissed

    UNDER_REVIEW --> UPHELD : Resolution insufficient
    UNDER_REVIEW --> OVERTURNED : Resolution valid
    UNDER_REVIEW --> REOPENED : Immediate reopen
    UNDER_REVIEW --> CLOSED : Review closes case

    UPHELD --> REOPENED : Case reopened
    UPHELD --> CLOSED : Case finalized

    OVERTURNED --> REOPENED : Overturned + reopen
    OVERTURNED --> CLOSED : Challenge denied, finalized

    REOPENED --> IN_PROGRESS : Work resumes

    CLOSED --> [*]
    REJECTED_WITH_REASON --> CHALLENGED : Citizen challenges rejection
```

---

## Data Flow: Complaint-to-Resolution Pipeline

```mermaid
sequenceDiagram
    participant C as Citizen
    participant API as FastAPI
    participant DB as PostgreSQL
    participant OBX as Outbox
    participant W as ARQ Worker
    participant AI as AI Provider
    participant O as Officer
    participant L as Dept Lead
    participant S as Supervisor

    C->>API: POST /complaints (+ Idempotency-Key)
    API->>DB: INSERT complaint (SUBMITTED)
    API->>OBX: Enqueue ComplaintSubmitted
    API-->>C: 201 Created + tracking number

    W->>OBX: Poll & consume event
    W->>AI: Triage request (PII-scrubbed)
    AI-->>W: Category, routing, priority, confidence
    W->>DB: Store ai_interpretation, routing_rec, priority_assessment
    W->>DB: complaint.status = TRIAGE_REVIEW

    O->>API: GET /complaints/{id}/ai-interpretation
    API-->>O: AI recommendations
    O->>API: POST .../routing/accept
    API->>DB: complaint.status = ROUTED, case created
    API->>OBX: Enqueue case.routed

    L->>API: POST /cases/{id}/transition (ACCEPTED_BY_LEAD)
    L->>API: POST /cases/{id}/assign (officer_id)
    API->>DB: case.status = IN_PROGRESS

    O->>API: POST /cases/{id}/resolve (evidence photos)
    API->>DB: ResolutionProposal + CITIZEN_REVIEW
    API-->>C: Notification: review your case

    alt Citizen Confirms
        C->>API: POST /cases/{id}/confirm
        API->>DB: case.status = CLOSED
    else Citizen Challenges
        C->>API: POST /cases/{id}/challenge
        API->>DB: case.status = CHALLENGED
        S->>API: POST /challenges/{id}/review (UPHELD)
        API->>DB: case.status = REOPENED -> IN_PROGRESS
    else Window Expires
        W->>API: POST /cases/worker/expire-review-windows
        API->>DB: case.status = CLOSED (auto)
    end
```

---

## Security Architecture

| Layer | Mechanism | Details |
|:---|:---|:---|
| **Transport** | TLS termination | Reverse proxy (nginx/traefik) in production |
| **Authentication** | Stateless JWT | Access (30min) + Refresh (7day), Argon2id password hashing |
| **Authorization** | RBAC middleware | `require_roles()` dependency on every route; 6 roles |
| **Object-Level AuthZ** | Service-layer checks | Citizens see only own complaints; officers see department scope |
| **Rate Limiting** | Redis sliding window | Tiered limits per endpoint class, graceful degradation |
| **CORS** | Allowlist-based | Configurable origins; no wildcard in production |
| **Input Validation** | Pydantic v2 strict | Type coercion disabled; RFC 7807 error responses |
| **Upload Security** | Magic-byte inspection | MIME whitelist, 15MB cap, executable rejection |
| **PII Protection** | Regex redaction | Phone, email, Aadhaar scrubbed before AI egress |
| **Prompt Injection** | XML boundary wrapping | Untrusted input wrapped in `<untrusted_citizen_submission>` tags |
| **Audit Integrity** | SHA-256 hash chain | Append-only with cryptographic tamper detection |
| **Idempotency** | Request hash dedup | SHA-256 body hash with 24h TTL; replay or 409 conflict |
| **Chaos Safety** | Environment guard | Chaos endpoints rejected with 403 in production |

---

## Infrastructure Dependencies

| Component | Version | Purpose |
|:---|:---|:---|
| Python | 3.12+ | Runtime |
| FastAPI | 0.110+ | Web framework |
| PostgreSQL | 16+ | Primary datastore |
| PostGIS | 3.4+ | Geospatial queries (ward lookup, nearby complaints) |
| pgvector | 0.7+ | Embedding similarity search (duplicate detection) |
| Redis | 7+ | Rate limiting, idempotency cache, ARQ job queue |
| MinIO | Latest | S3-compatible object storage for attachments |
| Alembic | 1.13+ | Database migrations |
| ARQ | 0.25+ | Async background workers |
