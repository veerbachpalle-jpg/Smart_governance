# Smart Governance: AI-Powered Municipal Grievance Intelligence and Accountability System

**Live demo (frontend):** https://smart-governance-woad.vercel.app/

> **The system recommends and assists. Humans decide.**
> It helps municipalities understand, prioritise, route, link and track citizen complaints through to verified resolution, with a full audit trail and a way for citizens to challenge official actions.

> ⚠️ **Note on accuracy:** configuration names, the project tree and the Windows commands have been checked against the codebase. Items still marked ⚠️ (API paths, scoring weights, thresholds, seeded demo credentials) are reference values; confirm them against `docs/openapi.json` and the source before publishing.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Hard MVP Boundary](#2-hard-mvp-boundary)
3. [Core Capabilities](#3-core-capabilities)
4. [System Architecture](#4-system-architecture)
5. [Tech Stack](#5-tech-stack)
6. [Module Breakdown](#6-module-breakdown)
7. [Complaint Lifecycle (State Machine)](#7-complaint-lifecycle-state-machine)
8. [Decision Engine](#8-decision-engine)
9. [AI Layer](#9-ai-layer)
10. [Data Model](#10-data-model)
11. [API Reference](#11-api-reference)
12. [Transparency, Audit and Accountability](#12-transparency-audit-and-accountability)
13. [Resilience and Manual Fallback](#13-resilience-and-manual-fallback)
14. [Security](#14-security)
15. [Evaluation Harness](#15-evaluation-harness)
16. [Project Structure](#16-project-structure)
17. [Getting Started](#17-getting-started)
18. [Configuration](#18-configuration)
19. [Testing](#19-testing)
20. [10-Minute Demo Script](#20-10-minute-demo-script)
21. [Known Limitations and Roadmap](#21-known-limitations-and-roadmap)

---

## 1. Overview

Municipal complaints are usually unstructured, multilingual, duplicated and poorly tracked. This system adds an intelligence and accountability layer:

| Problem | How the system addresses it |
|---|---|
| Complaints arrive in many languages and formats | Multilingual intake (English, Hindi, Kannada), language detection, translation with the original text preserved |
| Urgent safety issues get buried | Safety-aware priority engine where rule hits can only **raise** priority |
| Wrong department receives the complaint | Configurable, versioned routing rules plus AI suggestions with confidence and reasons |
| The same issue is reported many times | Duplicate and related-incident discovery (geo + semantic + category + time) |
| Multiple departments, nobody accountable | Multi-department cases with exactly **one accountable lead** |
| Citizens cannot see progress | Citizen-visible official activity timeline |
| Cases are closed without the problem being fixed | Closure requires verified evidence and a citizen confirmation or an unchallenged review window |
| No recourse against bad decisions | Challenge, independent review and reopen workflow |
| Decisions cannot be audited | Append-only, hash-chained audit log |

---

## 2. Hard MVP Boundary

These rules are enforced **in code**, not only in documentation.

| The system MAY | The system MUST NOT |
|---|---|
| Interpret, translate and summarise complaints | Autonomously make routing, priority, closure or merge decisions |
| Recommend a category, department and priority | State an unverified root cause as fact |
| Suggest duplicates and related incidents | Auto-merge duplicate complaints |
| Draft officer-facing reports | Mark a physical problem "resolved" without attached evidence and human verification |
| Fall back to manual triage on failure | Silently apply a default when AI fails or is unsure |

Every AI output is stored as a **recommendation** with status `PENDING`, `ACCEPTED`, `OVERRIDDEN` or `REJECTED`, plus the deciding human and the reason.

---

## 3. Core Capabilities

| # | Capability | Summary |
|---|---|---|
| 1 | Multilingual, location-aware submission | Text, map pin, photos, voice-to-text (frontend), ward lookup via PostGIS |
| 2 | AI-assisted interpretation | Category, sub-category, key facts, facts-vs-inferences report |
| 3 | Routing and priority | Versioned routing rules, safety-aware priority policies |
| 4 | Duplicate detection | Ranked candidates with a similarity breakdown, human link or dismiss |
| 5 | Multi-department coordination | Many departments per case, one accountable lead |
| 6 | Transparent history | INTERNAL vs CITIZEN_VISIBLE activity entries |
| 7 | Challenges and reopening | Independent reviewer, SLA timers, escalation |
| 8 | Auditability and fallback | Hash-chained audit log, manual triage, chaos simulation |

---

## 4. System Architecture

The backend is a **stateless modular monolith**. Long-running work is moved to workers through a transactional outbox, so a crash never loses a record.

```mermaid
flowchart TB
    subgraph Clients["Clients"]
        CP["Citizen Portal<br/>(React, mobile-first)"]
        SC["Staff Console<br/>(officer, lead, supervisor, admin, auditor)"]
    end

    subgraph Edge["Edge"]
        GW["CORS, rate limiting (Redis),<br/>request-ID, JWT auth"]
    end

    subgraph API["FastAPI API: stateless (/api/v1)"]
        direction TB
        R["Thin routers + Idempotency-Key + cursor pagination"]
        subgraph Modules["Modular monolith"]
            direction LR
            ID["identity"]
            CO["complaints"]
            AI["ai_assist"]
            RT["routing"]
            PR["priority"]
            DU["duplicates"]
            CA["cases"]
            AC["activity"]
            CH["challenges"]
            AU["audit"]
            NO["notifications"]
            EV["evaluation"]
        end
        R --> Modules
    end

    subgraph Async["Async processing"]
        OB[("Transactional outbox")]
        Q[["Redis queue"]]
        WK["ARQ worker<br/>(retry, backoff, idempotent)"]
        DL[("Dead-letter table")]
        SCH["Scheduled jobs<br/>(review expiry, SLA escalation)"]
    end

    subgraph AIL["AI layer (recommendations only)"]
        GR["Guardrails: PII redaction,<br/>injection-safe prompts, timeout,<br/>circuit breaker, kill switch"]
        LP{{"LLMProvider / EmbeddingProvider"}}
        GM["Gemini provider"]
        MK["MockProvider"]
    end

    subgraph Data["Data stores"]
        PG[("PostgreSQL<br/>PostGIS + pgvector")]
        MIO[("MinIO<br/>attachments, evidence")]
        RD[("Redis")]
    end

    CP --> GW
    SC --> GW
    GW --> R
    Modules -->|"state + event in ONE transaction"| PG
    Modules --> OB
    Modules --> MIO
    GW --- RD
    OB --> Q --> WK
    WK -->|"max attempts"| DL
    SCH --> WK
    WK --> AI
    WK --> DU
    WK --> NO
    AI --> GR --> LP
    LP --> GM
    LP --> MK
    DU --> PG
```

### 4.1 Architectural Principles

| Principle | Implementation |
|---|---|
| Modular monolith | Strict module boundaries; each module has `api / service / repository / schemas / models` |
| Thin routers | No business logic in routers; services hold rules; repositories hold DB access |
| Transactional outbox | Domain events are written in the same DB transaction as state changes, then published by a worker |
| Idempotency | `Idempotency-Key` header on all creating POST endpoints |
| Stateless API | Horizontally scalable; all long work happens in workers |
| Central state machine | One place defines allowed transitions, roles and required inputs |
| Provider abstraction | `LLMProvider` and `EmbeddingProvider` interfaces; swap Gemini for a mock or another vendor |
| Human in the loop | AI results are recommendations until a human decides |

### 4.2 Runtime Flow of One Complaint

```mermaid
sequenceDiagram
    autonumber
    actor Citizen
    participant API as FastAPI
    participant DB as PostgreSQL
    participant WK as Worker
    participant AI as AI layer
    actor Officer
    actor Lead as Lead dept

    Citizen->>API: POST /complaints (Idempotency-Key)
    API->>DB: complaint + audit + outbox event (one transaction)
    API-->>Citizen: tracking ID

    WK->>DB: poll outbox (ComplaintSubmitted)
    WK->>AI: redact PII, interpret, route, prioritise, find duplicates
    alt AI ok and confident
        AI-->>DB: recommendations (PENDING)
    else AI down, invalid, or low confidence
        AI-->>DB: move to MANUAL_TRIAGE
    end

    Officer->>API: accept / override (reason) / reject
    API->>DB: decision + audit + activity + outbox
    Note over API,DB: Complaint becomes ROUTED only after the human decision

    Lead->>API: accept, work, propose resolution (evidence)
    API->>DB: RESOLUTION_PROPOSED then CITIZEN_REVIEW
    Citizen->>API: confirm or challenge
    alt confirmed, or window expired with no challenge
        API->>DB: CLOSED (evidence verified by a human)
    else challenged
        API->>DB: CHALLENGED, independent review, UPHELD or OVERTURNED
    end
```

---

## 5. Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.12 | Typed, async, strong AI ecosystem |
| API framework | FastAPI + Pydantic v2 | Async, automatic OpenAPI, strict validation |
| ORM and migrations | SQLAlchemy 2.x (async), Alembic | Mature, explicit migrations |
| Database | PostgreSQL | Transactions, constraints, partial unique indexes |
| Geo | PostGIS | Radius queries, ward lookup from coordinates |
| Vector search | pgvector | Embedding similarity for duplicate detection |
| Queue and cache | Redis | Job queue, rate limiting |
| Worker | ARQ ⚠️ (or Celery) | Async job processing with retry |
| Object storage | MinIO (S3-compatible) | Complaint photos and resolution evidence |
| Auth | JWT (access + refresh), argon2 | Stateless auth, strong password hashing |
| AI | Gemini ⚠️ + deterministic MockProvider | Real inference and reproducible tests |
| Packaging | Docker Compose, Makefile | One-command local environment |
| Quality | pytest, httpx, ruff, mypy | Tests, linting, type checking |
| Frontend | React, TypeScript, Vite, Tailwind, shadcn/ui, TanStack Query, Leaflet | Citizen Portal and Staff Console |
| Frontend hosting | Vercel | Live demo at https://smart-governance-woad.vercel.app/ |

### 5.1 Frontend

The React app lives in `frontend/` and serves both experiences in one codebase.

| Experience | Users | Highlights |
|---|---|---|
| Citizen Portal | Citizens | Complaint wizard (text, map pin, photos), tracking, timeline, resolution review, challenges |
| Staff Console | Officer, lead, supervisor, admin, auditor | Triage queue, case view, challenge review, routing and policy editors, audit viewer, AI quality page |

| Frontend setting | Purpose |
|---|---|
| `VITE_API_BASE_URL` ⚠️ | Backend base URL |
| `VITE_USE_MOCKS` ⚠️ | `true` serves realistic mock data without a backend |

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

---

## 6. Module Breakdown

| Module | Responsibility | Key rules |
|---|---|---|
| `identity` | Registration, login, refresh, RBAC | Roles: citizen, officer, department_lead, supervisor, admin, auditor |
| `complaints` | Intake, attachments, geo, tracking | Original text is never overwritten |
| `ai_assist` | Language detection, translation, interpretation | Facts and inferences must be separated; no root-cause claims |
| `routing` | Versioned routing rules and recommendations | Routed only after a human decision |
| `priority` | Safety policies and priority assessment | Safety hits can only raise priority |
| `duplicates` | Embeddings, geo + semantic candidate search | Never auto-merge |
| `cases` | Case grouping, departments, state machine | Exactly one accountable lead |
| `activity` | Official activity history | INTERNAL vs CITIZEN_VISIBLE; append-only |
| `challenges` | Resolution proposals, challenges, reviews, reopen | Reviewer must differ from the original actor |
| `audit` | Hash-chained audit events | UPDATE and DELETE blocked at DB level |
| `notifications` ⚠️ | Pluggable delivery (confirm this exists as its own module or is handled inside the worker) | Failure never affects case state |
| `eval` | Datasets, eval runs, metrics | Safety-critical recall is the key metric |

### Layering inside each module

```mermaid
flowchart LR
    A["api (router)"] --> S["service (business rules)"]
    S --> R["repository (DB access)"]
    R --> M["models (SQLAlchemy)"]
    A --> SC["schemas (Pydantic)"]
    S --> E["domain events (outbox)"]
```

---

## 7. Complaint Lifecycle (State Machine)

```mermaid
stateDiagram-v2
    [*] --> SUBMITTED: citizen submits

    SUBMITTED --> AI_TRIAGE_PENDING: worker picks up event
    AI_TRIAGE_PENDING --> TRIAGE_REVIEW: AI recommendations ready
    AI_TRIAGE_PENDING --> MANUAL_TRIAGE: AI off, failed or low confidence
    MANUAL_TRIAGE --> TRIAGE_REVIEW: officer enters triage manually

    TRIAGE_REVIEW --> ROUTED: human accepts or overrides routing
    TRIAGE_REVIEW --> REJECTED_WITH_REASON: officer rejects (reason)

    ROUTED --> ACCEPTED_BY_LEAD: lead accepts
    ROUTED --> REASSIGN_REQUESTED: lead asks to reassign
    REASSIGN_REQUESTED --> ROUTED: supervisor reassigns

    ACCEPTED_BY_LEAD --> IN_PROGRESS: work starts
    IN_PROGRESS --> RESOLUTION_PROPOSED: evidence + notes + verifier
    RESOLUTION_PROPOSED --> CITIZEN_REVIEW: evidence verified, window opens

    CITIZEN_REVIEW --> CLOSED: citizen confirms OR window expires
    CITIZEN_REVIEW --> CHALLENGED: citizen challenges

    REJECTED_WITH_REASON --> CHALLENGED: citizen challenges rejection
    IN_PROGRESS --> CHALLENGED: citizen challenges action or priority

    CHALLENGED --> UNDER_REVIEW: independent reviewer assigned
    UNDER_REVIEW --> UPHELD: original decision stands
    UNDER_REVIEW --> OVERTURNED: decision reversed
    UPHELD --> CLOSED: resolution stands, evidence verified
    UPHELD --> IN_PROGRESS: in-progress challenge rejected
    OVERTURNED --> REOPENED: reopen event created
    REOPENED --> IN_PROGRESS: work resumes

    CLOSED --> [*]
```

### Transition table

| From | To | Allowed roles | Required input |
|---|---|---|---|
| SUBMITTED | AI_TRIAGE_PENDING | system (worker) | none |
| AI_TRIAGE_PENDING | TRIAGE_REVIEW | system | AI recommendations stored as PENDING |
| AI_TRIAGE_PENDING | MANUAL_TRIAGE | system | failure or low-confidence reason |
| MANUAL_TRIAGE | TRIAGE_REVIEW | officer | manual category, routing, priority |
| TRIAGE_REVIEW | ROUTED | officer, supervisor | routing decision (reason if overridden) |
| TRIAGE_REVIEW | REJECTED_WITH_REASON | officer, supervisor | written reason |
| ROUTED | ACCEPTED_BY_LEAD | department_lead | none |
| ROUTED | REASSIGN_REQUESTED | department_lead | reason |
| REASSIGN_REQUESTED | ROUTED | supervisor | new lead department, reason |
| ACCEPTED_BY_LEAD | IN_PROGRESS | department_lead, officer | none |
| IN_PROGRESS | RESOLUTION_PROPOSED | officer, department_lead | at least 1 evidence file, notes, verifying officer |
| RESOLUTION_PROPOSED | CITIZEN_REVIEW | verifying officer | evidence marked verified |
| CITIZEN_REVIEW | CLOSED | citizen, or system on expiry | verified evidence AND (confirmation OR expiry without challenge) |
| CITIZEN_REVIEW / REJECTED / IN_PROGRESS | CHALLENGED | citizen | reason, optional evidence |
| CHALLENGED | UNDER_REVIEW | supervisor, system | independent reviewer |
| UNDER_REVIEW | UPHELD / OVERTURNED | assigned reviewer | written reasoning; reviewer is not the original actor |
| OVERTURNED | REOPENED | system | reopen event |
| REOPENED | IN_PROGRESS | department_lead | none |

**Invariants enforced centrally**

- Every transition needs an actor, a reason where applicable, and writes an audit event and an activity entry in the same transaction.
- `CLOSED` needs verified evidence **and** (citizen confirmation **or** review window expiry without a challenge).
- Illegal transitions return a clear error code.

---

## 8. Decision Engine

The decision engine is a pipeline of **recommenders** followed by **human decision gates**. No recommender can move a case forward by itself.

```mermaid
flowchart TD
    A["Complaint submitted"] --> B["PII redaction"]
    B --> C["Language detection + translation"]
    C --> D["Interpretation<br/>(facts vs inferences)"]
    D --> E{"AI enabled and<br/>confidence >= threshold?"}
    E -- No --> M["MANUAL_TRIAGE queue"]
    E -- Yes --> F["Routing recommendation"]
    E -- Yes --> G["Priority assessment"]
    E -- Yes --> H["Duplicate search"]
    F --> I["Human gate: accept / override / reject"]
    G --> I
    H --> I
    M --> I
    I --> J["ROUTED, decision audited"]
```

### 8.1 Routing Engine

Inputs: category, sub-category, ward or geo-zone, effective date. Output: top-3 departments with confidence and reasons.

| Step | Description |
|---|---|
| 1. Rule match | Find active rules where `effective_from <= today <= effective_to` for the category and ward |
| 2. Specificity | A ward-specific rule beats a city-wide rule |
| 3. Model suggestion | The LLM proposes departments with confidence |
| 4. Merge | Rule matches and model suggestions are combined and ranked ⚠️ |
| 5. Output | Top-3, reasons, `rule_id`, `rule_version` stored |
| 6. Human gate | Officer accepts, overrides (reason required) or rejects |

Rules are **versioned**, so any past decision can be traced to the exact rule version used.

### 8.2 Priority Engine

```mermaid
flowchart LR
    T["Complaint text<br/>(original + translated)"] --> K["Safety rule matcher<br/>(EN / HI / KN keywords)"]
    T --> L["Model suggestion"]
    K --> X["Rule hits + minimum band"]
    L --> Y["Model band + reasoning"]
    X --> Z["final suggested band = max(rule floor, model band)"]
    Y --> Z
    Z --> H["Human decision recorded"]
```

| Property | Detail |
|---|---|
| Safety rule hits | e.g. exposed live wire, open manhole, flooding near a school |
| Monotonic rule | `suggested_band = max(rule_floor, model_band)`. Rules can only **raise** priority |
| Explainability | Stores rule hits, model reasoning, suggested band and final human-decided band |
| Safety queue | Safety-critical items are flagged in a dedicated priority queue endpoint |

Example priority bands ⚠️:

| Band | Meaning | Typical examples |
|---|---|---|
| P1 Critical | Immediate danger to life | Exposed live wire, open manhole on a road |
| P2 High | Serious disruption or risk | Major water main leak, flooding near a school |
| P3 Medium | Significant inconvenience | Streetlight out on a main road |
| P4 Low | Routine | Minor pothole, garbage on a side street |

### 8.3 Duplicate and Related-Incident Engine

Candidates must pass a geo-radius and time-window filter, then are scored on four signals.

| Signal | Source | Example weight ⚠️ |
|---|---|---|
| Geo proximity | PostGIS `ST_DWithin` and distance decay | 0.30 |
| Semantic similarity | pgvector cosine similarity of embeddings | 0.40 |
| Category match | Same category or sub-category | 0.20 |
| Time proximity | Recency within the window | 0.10 |

```
score = w_geo * geo + w_sem * semantic + w_cat * category + w_time * time
```

| Rule | Detail |
|---|---|
| Output | Ranked candidates, each with its breakdown for transparency |
| Human decision | Officer **links** or **dismisses**; never auto-merged |
| Citizen side | "Possible similar reports nearby" returns limited, non-sensitive fields; "same issue" adds support to the existing complaint |

### 8.4 Confidence and Abstention

| Condition | Behaviour |
|---|---|
| `AI_ENABLED=false` | Complaint goes to MANUAL_TRIAGE |
| Provider timeout or error, circuit breaker open | MANUAL_TRIAGE |
| Invalid JSON after one retry | MANUAL_TRIAGE |
| Confidence below threshold ⚠️ | MANUAL_TRIAGE, never a silent default |

---

## 9. AI Layer

### 9.1 Provider abstraction

```mermaid
classDiagram
    class LLMProvider {
        <<interface>>
        +detect_language(text)
        +translate(text, target)
        +interpret(text) InterpretationResult
        +suggest_route(context) RouteSuggestion
        +suggest_priority(context) PrioritySuggestion
    }
    class EmbeddingProvider {
        <<interface>>
        +embed(text) vector
    }
    class GeminiProvider
    class MockProvider
    LLMProvider <|.. GeminiProvider
    LLMProvider <|.. MockProvider
    EmbeddingProvider <|.. GeminiProvider
    EmbeddingProvider <|.. MockProvider
```

| Provider | Use |
|---|---|
| `GeminiProvider` | Real inference when an API key is configured |
| `MockProvider` | Deterministic keyword/rule logic for tests, CI and no-key environments |

### 9.2 Guardrails

| Guardrail | Purpose |
|---|---|
| PII redaction | Removes phone numbers, emails and Aadhaar-like numbers before the provider call |
| Prompt-injection safety | Complaint text is delimited and treated as **data**, never instructions |
| Schema validation | Pydantic validates output; retry once, then fall back to manual |
| Facts vs inferences | Schema separates `reported_facts` from `inferences`; post-check blocks root-cause claims |
| Timeouts and circuit breaker | Prevent a slow provider from stalling the system |
| Kill switch | `AI_ENABLED=false` disables all AI instantly |
| Versioned prompts | `prompts/v1/*.md`, so every result is reproducible |

### 9.3 What is stored for every AI result

| Field | Purpose |
|---|---|
| `model` | Which model produced it |
| `prompt_version` | Which prompt file version |
| `input_hash` | Detect identical inputs, support reproducibility |
| `raw_output` | Exact provider response |
| `parsed_output` | Validated structured result |
| `confidence` | Used for abstention and calibration |
| `latency_ms` | Performance monitoring |
| `status` + `decided_by` + `decision_reason` | Human oversight trail |

---

## 10. Data Model

### 10.1 Table groups

| Group | Tables |
|---|---|
| Identity | `users`, `citizen_profiles`, `departments`, `department_members` |
| Intake | `complaints`, `attachments` |
| AI and decisions | `ai_interpretations`, `routing_rules`, `routing_recommendations`, `priority_policies`, `priority_assessments`, `duplicate_suggestions` |
| Cases | `cases`, `case_departments`, `case_activities`, `citizen_updates` |
| Accountability | `resolution_proposals`, `citizen_challenges`, `challenge_reviews`, `reopen_events` |
| Infrastructure | `audit_events`, `outbox_events`, `dead_letter_events`, `idempotency_keys` |
| Evaluation | `eval_datasets`, `eval_runs`, `eval_results` |

### 10.2 Core entity relationships

```mermaid
erDiagram
    USERS ||--o| CITIZEN_PROFILES : has
    USERS ||--o{ DEPARTMENT_MEMBERS : belongs_to
    DEPARTMENTS ||--o{ DEPARTMENT_MEMBERS : has
    USERS ||--o{ COMPLAINTS : submits
    COMPLAINTS ||--o{ ATTACHMENTS : has
    COMPLAINTS ||--o{ AI_INTERPRETATIONS : has
    COMPLAINTS ||--o{ ROUTING_RECOMMENDATIONS : has
    COMPLAINTS ||--o{ PRIORITY_ASSESSMENTS : has
    COMPLAINTS ||--o{ DUPLICATE_SUGGESTIONS : source
    CASES ||--o{ COMPLAINTS : groups
    CASES ||--o{ CASE_DEPARTMENTS : involves
    DEPARTMENTS ||--o{ CASE_DEPARTMENTS : participates
    CASES ||--o{ CASE_ACTIVITIES : records
    CASES ||--o{ RESOLUTION_PROPOSALS : has
    CASES ||--o{ CITIZEN_CHALLENGES : challenged_by
    CITIZEN_CHALLENGES ||--o| CHALLENGE_REVIEWS : reviewed_in
    CHALLENGE_REVIEWS ||--o| REOPEN_EVENTS : may_trigger
    USERS ||--o{ AUDIT_EVENTS : acts
    OUTBOX_EVENTS ||--o| DEAD_LETTER_EVENTS : fails_into
    EVAL_DATASETS ||--o{ EVAL_RUNS : used_by
    EVAL_RUNS ||--o{ EVAL_RESULTS : produces
```

### 10.3 Important constraints

| Constraint | Table | Why |
|---|---|---|
| Partial unique index on `is_accountable_lead = true` per case | `case_departments` | Exactly one accountable lead |
| GiST index on geo point | `complaints` | Fast radius queries |
| Vector index | `ai_interpretations` | Fast similarity search |
| No UPDATE or DELETE (trigger or revoked grant) | `audit_events`, `case_activities` | Tamper resistance |
| Reviewer ≠ original actor (service + test) | `challenge_reviews` | Independent review |
| Unique `(key, user, endpoint)` | `idempotency_keys` | Safe retries |

---

## 11. API Reference

Base path: `/api/v1`. Interactive docs at `/docs`; the contract is in `docs/openapi.json`. ⚠️ Confirm exact paths against `docs/openapi.json`.

### 11.1 Conventions

| Topic | Convention |
|---|---|
| Auth | `Authorization: Bearer <access_token>` |
| Idempotency | `Idempotency-Key: <uuid>` on creating POSTs; same key + same body replays the response; same key + different body returns `409` |
| Pagination | Cursor-based: `?limit=20&cursor=<opaque>`; response includes `next_cursor` |
| Filtering and sorting | Query parameters such as `?status=ROUTED&sort=-created_at` |
| Request tracing | `X-Request-ID` echoed in responses and logs |
| Error format | `{ "error": { "code": "STRING", "message": "...", "details": {} , "request_id": "..." } }` |

### 11.2 Identity

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/auth/register` | public | Register a citizen |
| POST | `/auth/login` | public | Issue access and refresh tokens |
| POST | `/auth/refresh` | public | Rotate tokens |
| GET | `/auth/me` | any | Current user and role |
| GET/POST | `/admin/users`, `/admin/departments` | admin | Manage users and departments |

### 11.3 Complaints

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/complaints` | citizen | Submit complaint (Idempotency-Key required) |
| GET | `/complaints` | citizen / staff | List (citizens see only their own) |
| GET | `/complaints/{id}` | owner / staff | Complaint detail |
| GET | `/track/{tracking_id}` | public | Status only, no personal data |
| POST | `/complaints/{id}/attachments` | owner | Upload photo or PDF (type and size validated) |
| GET | `/complaints/{id}/similar` | citizen | Possible similar reports nearby (limited fields) |
| POST | `/complaints/{id}/support` | citizen | "This is the same issue" |

### 11.4 AI assist, routing and priority

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/complaints/{id}/ai-interpretation` | staff | View interpretation (facts vs inferences) |
| POST | `/complaints/{id}/ai-interpretation/accept` | officer | Accept recommendation |
| POST | `/complaints/{id}/ai-interpretation/override` | officer | Override (reason required) |
| POST | `/complaints/{id}/ai-interpretation/reject` | officer | Reject recommendation |
| GET | `/complaints/{id}/routing` | staff | Routing recommendation (top-3, reasons, rule version) |
| POST | `/complaints/{id}/routing/decision` | officer, supervisor | Accept, override or reject routing |
| GET | `/complaints/{id}/priority` | staff | Rule hits, reasoning, suggested band |
| POST | `/complaints/{id}/priority/decision` | officer, supervisor | Decide priority |
| GET | `/priority/queue` | staff | Safety-critical queue |
| GET/POST/PUT | `/admin/routing-rules` | admin | Versioned routing rules |
| GET/POST/PUT | `/admin/priority-policies` | admin | Safety policy editor |

### 11.5 Duplicates

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/complaints/{id}/duplicates` | staff | Ranked candidates with similarity breakdown |
| POST | `/duplicates/{id}/link` | officer | Link as related |
| POST | `/duplicates/{id}/dismiss` | officer | Dismiss suggestion |

### 11.6 Cases and activity

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/cases` | officer | Create case from a complaint |
| POST | `/cases/{id}/complaints` | officer | Link complaints into a case |
| POST | `/cases/{id}/departments` | supervisor | Add a participating department |
| PUT | `/cases/{id}/lead` | supervisor | Set the single accountable lead |
| POST | `/cases/{id}/transition` | role-checked | Perform a state transition |
| POST | `/cases/{id}/activities` | staff | Add activity (INTERNAL or CITIZEN_VISIBLE) |
| GET | `/cases/{id}` | staff | Full staff view for the role |
| GET | `/complaints/{id}/timeline` | citizen owner | Only CITIZEN_VISIBLE entries |

### 11.7 Resolution and challenges

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/cases/{id}/resolution` | officer, lead | Propose resolution (evidence + notes + verifier) |
| POST | `/resolutions/{id}/verify` | verifying officer | Mark evidence verified, open citizen review |
| POST | `/resolutions/{id}/confirm` | citizen | Confirm the fix |
| POST | `/cases/{id}/challenges` | citizen | Challenge an action, rejection, resolution or priority |
| GET | `/challenges/{id}` | citizen / reviewer | Challenge status |
| GET | `/challenges/queue` | reviewer, supervisor | Review queue |
| POST | `/challenges/{id}/review` | independent reviewer | UPHELD or OVERTURNED with reasoning |

### 11.8 Audit, admin and evaluation

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/audit/events` | auditor, admin | Filterable, paginated audit log |
| GET | `/audit/verify` | auditor, admin | Hash-chain integrity pass/fail, first broken row |
| GET/POST | `/admin/chaos` | admin (non-prod) | View or activate failure simulation |
| GET | `/triage/manual-queue` | officer | MANUAL_TRIAGE queue |
| POST | `/complaints/{id}/manual-triage` | officer | Enter category, routing and priority manually |
| GET | `/eval/runs` | admin, auditor | Evaluation run history |
| GET | `/eval/runs/{id}` | admin, auditor | Metrics, confusion matrix, false negatives |
| GET | `/health`, `/ready` | public | Liveness and readiness |

### 11.9 Example requests

**Submit a complaint**

```http
POST /api/v1/complaints
Authorization: Bearer <token>
Idempotency-Key: 6f1b0e0a-3c1d-4a56-9d62-1f3a7a1c9b11
Content-Type: application/json

{
  "text": "ರಸ್ತೆಯಲ್ಲಿ ತೆರೆದ ಮ್ಯಾನ್‌ಹೋಲ್ ಇದೆ, ಶಾಲೆಯ ಹತ್ತಿರ",
  "language": "kn",
  "location": { "lat": 22.9676, "lng": 76.0534 },
  "address": "Near Govt School, Main Road",
  "channel": "web"
}
```

**Response**

```json
{
  "id": "c3a1...",
  "tracking_id": "GRV-2026-000123",
  "status": "SUBMITTED",
  "created_at": "2026-10-15T10:22:31Z"
}
```

**Override a routing recommendation**

```http
POST /api/v1/complaints/{id}/routing/decision
{
  "decision": "OVERRIDDEN",
  "department_id": "dept_drainage",
  "reason": "Manhole belongs to the drainage network, not roads."
}
```

**Challenge a proposed resolution**

```http
POST /api/v1/cases/{id}/challenges
{
  "target_type": "resolution",
  "target_id": "res_91...",
  "reason": "The pothole was filled but already sinking again.",
  "attachment_ids": ["att_5c..."]
}
```

---

## 12. Transparency, Audit and Accountability

### 12.1 Visibility model

| Viewer | Sees |
|---|---|
| Citizen | Only `CITIZEN_VISIBLE` activities for their own complaints, plus a status timeline |
| Officer / lead | Everything their role and department permit |
| Supervisor | Cross-department view, escalations |
| Auditor | Read-only audit log and integrity verification |

### 12.2 Hash-chained audit log

Each `audit_events` row stores the hash of the previous row, so editing any past row breaks every later hash.

```mermaid
flowchart LR
    E1["Event 1<br/>prev: 0000<br/>hash: H1"] --> E2["Event 2<br/>prev: H1<br/>hash: H2"] --> E3["Event 3<br/>prev: H2<br/>hash: H3"] --> E4["Event 4<br/>prev: H3<br/>hash: H4"]
```

```
hash_n = SHA256( hash_(n-1) || actor || event_type || entity || payload || timestamp )
```

`GET /audit/verify` recomputes the chain and reports pass/fail and the first broken row.

### 12.3 Challenge and review process

```mermaid
flowchart TD
    A["Citizen challenges an action"] --> B["Case: CHALLENGED"]
    B --> C{"Reviewer = original actor?"}
    C -- Yes --> X["Blocked by service rule"]
    C -- No --> D["UNDER_REVIEW with SLA timer"]
    D --> E{"SLA breached?"}
    E -- Yes --> F["Auto-escalate to supervisor"]
    E -- No --> G["Reviewer decides"]
    F --> G
    G --> H["UPHELD"]
    G --> I["OVERTURNED"]
    I --> J["Reopen event, case REOPENED then IN_PROGRESS"]
    H --> K["Original decision stands, citizen notified"]
```

---

## 13. Resilience and Manual Fallback

### 13.1 Outbox and retry

```mermaid
flowchart LR
    S["Service: state change"] --> T[("DB transaction")]
    T --> O["outbox_events row"]
    O --> W["Worker publishes"]
    W -->|success| D["Mark DONE"]
    W -->|failure| R["Retry with exponential backoff"]
    R -->|max attempts| DL[("dead_letter_events")]
```

| Failure | Behaviour | Record loss? |
|---|---|---|
| AI disabled or down | MANUAL_TRIAGE queue | None |
| AI returns garbage | One retry, then MANUAL_TRIAGE | None |
| Worker crashes mid-job | Outbox event reprocessed idempotently | None, no duplicate effects |
| Notification delivery fails | Retries, then dead-letter; case unaffected | None |
| DB error mid-transition | Transaction rolls back; client retries safely with the same Idempotency-Key | None |

### 13.2 Failure simulation (`/admin/chaos`)

Available only when `ENV != production`.

| Simulation | Effect |
|---|---|
| Disable AI | Forces manual fallback |
| AI garbage | Provider returns invalid output |
| Delay or stop worker | Tests outbox durability |
| Fail notifications | Tests retry and dead-letter |
| Inject DB error | Fails a named operation to test rollback |

---

## 14. Security

| Area | Measure |
|---|---|
| Passwords | argon2 hashing |
| Sessions | Short-lived JWT access tokens plus refresh tokens |
| Authorization | RBAC enforced in the **service layer**; object-level checks (citizens only see their own data) |
| Abuse prevention | Redis-backed rate limiting |
| Uploads | Type allow-list (jpg, png, webp, pdf), size limits, executable content rejected |
| AI safety | PII redaction, prompt-injection-safe handling |
| Secrets | Environment variables only; `.env.example` provided; nothing committed |
| Network | Configurable CORS |
| Integrity | Append-only audit and activity tables |

---

## 15. Evaluation Harness

Run with `make eval`. Reports are written to `reports/` as JSON and Markdown.

### 15.1 Dataset ⚠️

| Property | Target |
|---|---|
| Size | 200+ synthetic complaints |
| Languages | English, Hindi, Kannada, plus code-mixed |
| Special samples | Vague text, adversarial and prompt-injection samples |
| Labels | `language`, `category`, `correct_department`, `safety_critical`, `expected_priority_band`, `duplicate_group_id` |
| Safety-critical examples | At least 40 |

### 15.2 Metrics

| Metric | Definition | Why it matters |
|---|---|---|
| Language accuracy | Correct language / total | Intake quality |
| Category accuracy | Correct category / total | Interpretation quality |
| Routing top-1 / top-3 | Correct department in first / first three | Routing quality |
| **Safety-critical recall** | True safety-critical flagged / all safety-critical | **Primary metric**; false negatives are listed explicitly |
| Priority band agreement | Suggested band = expected band | Priority quality |
| Duplicate precision and recall@k | Correct links among suggestions / true duplicates found | Duplicate quality |
| Abstention rate | Share sent to manual triage | Safe degradation |
| Calibration | Accuracy per confidence bucket | Is confidence trustworthy? |
| Latency | p50, p95, p99 | Performance |

```
Safety recall = TP / (TP + FN)
```

A configurable minimum safety recall causes `make eval` to **fail**, like a CI gate. The report compares `MockProvider` against the real provider.

---

## 16. Project Structure

```
Smart_governance/
├── app/
│   ├── main.py
│   ├── config.py             # pydantic-settings configuration
│   ├── core/                 # security, rate_limit, outbox, worker, chaos, errors
│   ├── db/                   # session, base
│   └── modules/              # identity, complaints, ai_assist, routing, priority,
│                             # duplicates, cases, activity, challenges, audit, eval
│                             # (each: api / service / repository / schemas / models)
├── frontend/                 # React + TypeScript + Vite + Tailwind + TanStack Query
├── prompts/v1/               # versioned prompts
├── alembic/                  # database migrations
├── data/eval/                # labelled evaluation dataset
├── reports/                  # evaluation reports
├── tests/                    # unit, integration, failure-simulation tests
├── Dockerfile
├── docker-compose.yml
├── Makefile                  # Linux / macOS
├── make.bat                  # Windows
└── .env.example
```

| Path | Notes |
|---|---|
| `app/core/outbox.py` | Transactional outbox writer and publisher |
| `app/core/worker.py` | Background worker, retry and dead-letter handling |
| `app/core/chaos.py` | Failure simulation switches |
| `app/config.py` | All environment-driven settings |

---

## 17. Getting Started

### Prerequisites

| Tool | Version |
|---|---|
| Docker and Docker Compose | recent |
| Make | any |
| Python (only for local, non-Docker runs) | 3.12 |

### Quick start

```bash
git clone https://github.com/veerbachpalle-jpg/Smart_governance.git
cd Smart_governance

cp .env.example .env     # edit secrets and keys
make up                  # start api, worker, postgres, redis, minio
make migrate             # apply Alembic migrations
make seed                # departments, rules, demo users, demo complaints
```

**On Windows (PowerShell or CMD)**, where GNU `make` may not be installed, use the bundled batch file:

```bat
make.bat up
make.bat migrate
make.bat seed
```

Open the API docs at `http://localhost:8000/docs`.

### Makefile targets

| Command | Purpose |
|---|---|
| `make up` / `make down` | Start or stop the stack |
| `make migrate` | Run database migrations |
| `make seed` | Load demo data |
| `make test` | Run the test suite |
| `make lint` | ruff and mypy |
| `make eval` | Run the evaluation harness |

On Windows, replace `make` with `make.bat` (for example `make.bat test`).

### Demo users (from seed) ⚠️

| Role | Email | Password |
|---|---|---|
| Citizen | citizen@example.com | change-me |
| Officer | officer@example.com | change-me |
| Department lead | lead@example.com | change-me |
| Supervisor | supervisor@example.com | change-me |
| Admin | admin@example.com | change-me |
| Auditor | auditor@example.com | change-me |

> Change all seeded passwords outside local development.

---

## 18. Configuration

| Variable | Description | Example |
|---|---|---|
| `ENV` | `development`, `test` or `production` | `development` |
| `DATABASE_URL` | Async Postgres URL | `postgresql+asyncpg://user:pass@postgres/grievance` |
| `REDIS_URL` | Redis connection | `redis://redis:6379/0` |
| `MINIO_ENDPOINT` ⚠️ | Object storage endpoint | `minio:9000` |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | Object storage credentials | |
| `JWT_SECRET_KEY` | Signing secret | long random string |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | Token lifetimes | `15` / `7` |
| `AI_ENABLED` | Kill switch | `true` |
| `AI_PROVIDER` | `gemini` or `mock` | `mock` |
| `GEMINI_API_KEY` | Provider key (empty uses mock) | |
| `AI_CONFIDENCE_THRESHOLD` | Below this goes to manual triage | `0.6` ⚠️ |
| `AI_TIMEOUT_SECONDS` | Provider timeout | `20` |
| `CITIZEN_REVIEW_WINDOW_HOURS` | Time-boxed review window | `72` ⚠️ |
| `CHALLENGE_SLA_HOURS` | Reviewer SLA before escalation | `48` ⚠️ |
| `EVAL_MIN_SAFETY_RECALL` | CI gate for `make eval` | `0.95` ⚠️ |
| `MAX_UPLOAD_SIZE_MB` | Maximum attachment size in MB (integer) | `15` |
| `CORS_ORIGINS` | Allowed frontend origins | `http://localhost:5173` |

---

## 19. Testing

| Type | Covers |
|---|---|
| Unit | State machine table, routing rule versioning, priority "only raises" rule |
| Integration | Full lifecycle end to end, RBAC and object-level authorization |
| AI | Invalid JSON fallback, prompt-injection sample, PII redaction, kill switch, low confidence to manual |
| Infrastructure | Outbox retry and dead-letter, audit tamper detection, idempotency replay and conflict, pagination |
| Failure simulation | AI down, AI garbage, worker killed mid-job, notification failure, DB error mid-transition |

```bash
make test
```

---

## 20. 10-Minute Demo Script

| Minute | Step | What to show |
|---|---|---|
| 0-1 | Setup | `make up`, `make migrate`, `make seed` |
| 1-3 | Citizen submits | Kannada complaint with a map pin and photo; tracking ID returned |
| 3-4 | AI triage | Facts vs inferences report, routing and priority suggestions, safety rule hit |
| 4-5 | Human decision | Officer overrides routing with a reason; audit entry appears |
| 5-6 | Case work | Lead accepts; second department added; internal note vs citizen-visible update |
| 6-7 | Resolution | Officer proposes resolution with evidence; verifier confirms |
| 7-8 | Challenge | Citizen challenges; independent reviewer overturns; case reopens |
| 8-9 | Chaos | Disable AI via `/admin/chaos`; new complaint lands in manual triage; no data lost |
| 9-10 | Proof | `GET /audit/verify` passes; `make eval` report with safety recall |

---

## 21. Known Limitations and Roadmap

| Area | Current MVP | Next step |
|---|---|---|
| AI provider | Single real provider plus mock | Add more providers and fine-tuned models |
| Channels | Web | SMS, WhatsApp, IVR |
| Notifications | Console/log channel | SMS and email gateways |
| Dataset | Synthetic | Anonymised real complaints with consent |
| Duplicates | Single-embedding similarity | Learned ranking model |
| Geo | Synthetic ward polygons | Official municipal boundaries |
| Analytics | Basic dashboards | Hotspot and trend analysis |
| Scale | Modular monolith | Extract hot modules into services if needed |

---

