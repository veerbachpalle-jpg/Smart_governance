# AI-Powered Municipal Grievance Intelligence & Accountability System

> Transform municipal grievance handling by augmenting human decision-makers with AI-powered triage, evidence-backed resolution, and tamper-evident audit trails.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)]()
[![Tests](https://img.shields.io/badge/tests-83%20passed-brightgreen.svg)]()
[![Ruff](https://img.shields.io/badge/lint-ruff-purple.svg)]()

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Running Locally](#running-locally)
- [Demo: 10-Minute Full Lifecycle](#demo-10-minute-full-lifecycle)
- [Testing](#testing)
- [Evaluation Harness](#evaluation-harness)
- [API Documentation](#api-documentation)
- [Architecture Decision Records](#architecture-decision-records)
- [Known Gaps & Future Work](#known-gaps--future-work)

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url> && cd ai-synergic

# 2. Create virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment template
cp .env.example .env
# Edit .env if needed (defaults work for local dev with SQLite)

# 5. Start infrastructure (optional: full stack with PostgreSQL/Redis/MinIO)
make up   # docker compose up -d

# 6. Run migrations (if using PostgreSQL)
make migrate

# 7. Seed demo data
make seed

# 8. Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 9. Run tests
make test

# 10. Run lint + type checks
make lint
```

---

## Architecture

The system is a **modular monolith** with 12 domain modules, a transactional outbox for reliable async processing, and a SHA-256 hash-chain audit trail. See [docs/architecture.md](docs/architecture.md) for full diagrams.

### Core Principles

| Principle | Enforcement |
|:---|:---|
| **AI Recommends Only** | AI outputs stored as `PENDING` recommendations; human officer must `ACCEPT`, `OVERRIDE`, or `REJECT` |
| **Evidence-Backed Closure** | Case cannot close without verified remediation photos + officer sign-off |
| **Tamper-Evident Audit** | Every state transition hashed into append-only chain with cryptographic linking |
| **Fail-Safe Degradation** | AI failures route to `MANUAL_TRIAGE` queue; system never blocks on AI |
| **Single Accountable Lead** | Every case has exactly one lead department (DB constraint + service invariant) |

### Key Decisions (ADRs)

| ADR | Decision |
|:---|:---|
| [ADR-001](docs/adr/001-modular-monolith.md) | Modular monolith over microservices |
| [ADR-002](docs/adr/002-transactional-outbox.md) | Transactional outbox over message broker |
| [ADR-003](docs/adr/003-pgvector-duplicate-detection.md) | pgvector for duplicate detection |
| [ADR-004](docs/adr/004-hash-chain-audit.md) | SHA-256 hash chain for audit immutability |
| [ADR-005](docs/adr/005-provider-abstraction.md) | Provider abstraction with fail-safe degradation |
| [ADR-006](docs/adr/006-state-machine.md) | Central state machine for case lifecycle |

---

## Project Structure

```
app/
├── config.py                    # Pydantic settings (env-driven)
├── main.py                      # FastAPI app, middleware, router mounts
├── core/
│   ├── security.py              # Argon2 hashing, JWT tokens
│   ├── dependencies.py          # Auth + RBAC dependencies
│   ├── middleware.py             # Request-ID, RFC 7807 error handlers
│   ├── rate_limit.py            # Redis sliding-window rate limiter
│   ├── outbox.py                # Transactional outbox + processor
│   ├── idempotency.py           # Idempotency-Key validation
│   ├── pagination.py            # Keyset cursor pagination
│   ├── chaos.py                 # Chaos simulation engine
│   └── errors.py                # RFC 7807 exception classes
├── modules/
│   ├── identity/                # Users, Auth, RBAC
│   ├── complaints/              # Submissions, Attachments, Geo
│   ├── ai_assist/               # AI Triage, Guardrails, Providers
│   ├── routing/                 # Rules, Recommendations
│   ├── priority/                # Policies, Safety Invariants
│   ├── duplicates/              # pgvector, Spatial, Candidates
│   ├── cases/                   # Lifecycle, State Machine
│   ├── activity/                # Immutable Logs, Timeline
│   ├── challenges/              # Resolutions, Disputes, Reviews
│   ├── audit/                   # Hash Chain, Verification
│   ├── notifications/           # Pluggable Channels
│   └── evaluation/              # Benchmarks, Metrics
├── db/
│   ├── session.py               # SQLAlchemy async engine
│   ├── base.py                  # Declarative base
│   └── seed.py                  # Demo data seeder
docs/
├── architecture.md              # Mermaid architecture diagrams
├── api-endpoints.md             # Endpoint specification
├── state-machine.md             # State transition matrix
├── openapi.json                 # Generated OpenAPI 3.1 spec
├── adr/                         # Architecture Decision Records
└── PROGRESS.md                  # Milestone tracker
tests/
├── conftest.py                  # Fixtures (SQLite, users, tokens)
├── unit/                        # Pure unit tests
└── integration/                 # API + service integration tests
```

---

## Configuration

All configuration is driven by environment variables (loaded from `.env`):

| Variable | Default | Description |
|:---|:---|:---|
| `ENVIRONMENT` | `development` | `development`, `staging`, `production` |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async database connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for rate limiting, queues, idempotency |
| `JWT_SECRET_KEY` | *(change in prod!)* | HMAC-SHA256 signing key for JWT tokens |
| `GEMINI_API_KEY` | `None` | Google Gemini API key (optional; uses MockProvider if unset) |
| `AI_ENABLED` | `true` | Kill switch for AI triage |
| `AI_CONFIDENCE_THRESHOLD` | `0.7` | Below this, complaints go to MANUAL_TRIAGE |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed origins |
| `RATE_LIMIT_ENABLED` | `true` | Enable Redis rate limiting |
| `MAX_UPLOAD_SIZE_MB` | `15` | Maximum file upload size |

> **Security**: `.env` is in `.gitignore`. Never commit secrets. Use `.env.example` as a template.

---

## Running Locally

### Option A: SQLite (Zero Dependencies)

```bash
# .env already defaults to SQLite for easy local dev
DATABASE_URL=sqlite+aiosqlite:///./test_grievance.db

# Just start the server
uvicorn app.main:app --reload
```

### Option B: Full Stack (Docker Compose)

```bash
# Start PostgreSQL + PostGIS + pgvector, Redis, MinIO
docker compose up -d

# Run migrations
alembic upgrade head

# Seed demo accounts
python -m app.db.seed

# Start API
uvicorn app.main:app --reload
```

### Demo Accounts (seeded by `make seed`)

| Role | Email | Password |
|:---|:---|:---|
| Citizen | `citizen@demo.municipal.gov` | `CitizenDemo123!` |
| Officer | `officer@demo.municipal.gov` | `OfficerDemo123!` |
| Dept Lead | `lead@demo.municipal.gov` | `LeadDemo123!` |
| Supervisor | `supervisor@demo.municipal.gov` | `SupervisorDemo123!` |
| Admin | `admin@demo.municipal.gov` | `AdminDemo123!` |
| Auditor | `auditor@demo.municipal.gov` | `AuditorDemo123!` |

---

## Demo: 10-Minute Full Lifecycle

This script walks through the complete grievance lifecycle using `curl`. Start the server first: `uvicorn app.main:app --reload`

### Step 1: Citizen Submits Complaint (~1 min)

```bash
# 1a. Register a citizen
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "demo.citizen@example.com",
    "phone_number": "+919876543210",
    "password": "DemoCitizen123!",
    "full_name": "Priya Sharma",
    "preferred_language": "en"
  }'

# 1b. Login as citizen
CITIZEN_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "demo.citizen@example.com", "password": "DemoCitizen123!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Citizen token: $CITIZEN_TOKEN"

# 1c. Submit a grievance
COMPLAINT=$(curl -s -X POST http://localhost:8000/api/v1/complaints \
  -H "Authorization: Bearer $CITIZEN_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-complaint-001" \
  -d '{
    "title": "Massive pothole on MG Road near Central Mall",
    "description": "There is a dangerous 3-foot deep pothole on MG Road near Central Mall junction. Multiple two-wheelers have fallen. Urgent repair needed before someone gets seriously injured.",
    "latitude": 12.9716,
    "longitude": 77.5946,
    "address": "MG Road, near Central Mall, Bengaluru 560001"
  }')

COMPLAINT_ID=$(echo $COMPLAINT | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Complaint ID: $COMPLAINT_ID"
echo "Status: $(echo $COMPLAINT | python -c "import sys,json; print(json.load(sys.stdin)['status'])")"
```

### Step 2: AI Triage Runs Automatically (~1 min)

The outbox worker processes `ComplaintSubmitted` and runs the AI pipeline:
- Language detection
- Category extraction (Roads & Infrastructure)
- Priority assessment (HIGH — safety hazard)
- Routing recommendation (Public Works Department)

```bash
# 2a. Login as officer
OFFICER_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "officer@demo.municipal.gov", "password": "OfficerDemo123!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2b. View AI interpretation
curl -s http://localhost:8000/api/v1/complaints/$COMPLAINT_ID/ai-interpretation \
  -H "Authorization: Bearer $OFFICER_TOKEN" | python -m json.tool
```

### Step 3: Human Routing Decision (~1 min)

```bash
# 3a. Officer accepts AI routing recommendation
curl -s -X POST http://localhost:8000/api/v1/complaints/$COMPLAINT_ID/routing/accept \
  -H "Authorization: Bearer $OFFICER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'

# The complaint is now ROUTED and a Case is created
# 3b. View the case
curl -s http://localhost:8000/api/v1/cases/$COMPLAINT_ID \
  -H "Authorization: Bearer $OFFICER_TOKEN" | python -m json.tool
```

### Step 4: Department Lead Accepts & Assigns (~1 min)

```bash
# 4a. Login as department lead
LEAD_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "lead@demo.municipal.gov", "password": "LeadDemo123!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 4b. Accept the case (ROUTED -> ACCEPTED_BY_LEAD)
# (Use the case_id from the previous response)
CASE_ID="<paste-case-id-here>"
curl -s -X POST http://localhost:8000/api/v1/cases/$CASE_ID/transition \
  -H "Authorization: Bearer $LEAD_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_state": "ACCEPTED_BY_LEAD"}'

# 4c. Assign an officer and move to IN_PROGRESS
curl -s -X POST http://localhost:8000/api/v1/cases/$CASE_ID/assign \
  -H "Authorization: Bearer $LEAD_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"officer_id": "<officer-user-id>"}'
```

### Step 5: Evidence & Resolution Proposal (~2 min)

```bash
# 5a. Upload remediation photo evidence
curl -s -X POST http://localhost:8000/api/v1/complaints/attachments/upload \
  -H "Authorization: Bearer $OFFICER_TOKEN" \
  -F "file=@remediation_photo.jpg"

# 5b. Propose resolution with evidence (IN_PROGRESS -> RESOLUTION_PROPOSED -> CITIZEN_REVIEW)
curl -s -X POST http://localhost:8000/api/v1/cases/$CASE_ID/resolve \
  -H "Authorization: Bearer $OFFICER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "summary_notes": "Pothole filled with hot-mix asphalt and compacted. Road surface restored to grade.",
    "evidence_attachment_ids": ["<attachment-id>"],
    "officer_verified": true
  }'
```

### Step 6: Citizen Reviews & Closes (~1 min)

```bash
# 6a. Citizen confirms satisfaction (CITIZEN_REVIEW -> CLOSED)
curl -s -X POST http://localhost:8000/api/v1/cases/$CASE_ID/confirm \
  -H "Authorization: Bearer $CITIZEN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"satisfaction_note": "The pothole has been properly filled. Thank you!"}'

echo "=== CASE CLOSED ==="
```

### Step 7: Challenge & Reopen (~2 min)

```bash
# 7a. (Alternative to Step 6) Citizen challenges the resolution
curl -s -X POST http://localhost:8000/api/v1/cases/$CASE_ID/challenge \
  -H "Authorization: Bearer $CITIZEN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "challenge_type": "RESOLUTION",
    "reason": "The repair was superficial. The pothole has already re-opened after one rain.",
    "evidence_attachment_ids": []
  }'

# 7b. Login as supervisor
SUPERVISOR_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "supervisor@demo.municipal.gov", "password": "SupervisorDemo123!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 7c. View challenge queue
curl -s http://localhost:8000/api/v1/challenges/queue \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" | python -m json.tool

# 7d. Supervisor upholds the challenge (case reopens)
CHALLENGE_ID="<paste-challenge-id>"
curl -s -X POST http://localhost:8000/api/v1/challenges/$CHALLENGE_ID/review \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "outcome": "UPHELD",
    "rationale": "Citizen evidence confirms repair has failed. Case reopened for proper remediation."
  }'

echo "=== CASE REOPENED ==="
```

### Step 8: Chaos Simulation (~1 min)

```bash
# 8a. Login as admin
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@demo.municipal.gov", "password": "AdminDemo123!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 8b. Simulate AI outage
curl -s -X POST http://localhost:8000/api/v1/admin/chaos \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"disable_ai": true}'

# 8c. Submit a complaint during outage — it should go to MANUAL_TRIAGE
curl -s -X POST http://localhost:8000/api/v1/complaints \
  -H "Authorization: Bearer $CITIZEN_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: chaos-test-001" \
  -d '{
    "title": "Street light not working on Brigade Road",
    "description": "Street light pole #247 on Brigade Road has been dark for 3 nights.",
    "latitude": 12.9720,
    "longitude": 77.6070
  }'
# Status should be MANUAL_TRIAGE

# 8d. Reset chaos
curl -s -X POST http://localhost:8000/api/v1/admin/chaos/reset \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Step 9: Evaluation Harness (~1 min)

```bash
# Run the evaluation benchmark with the mock provider
make eval

# Or with options:
python -m app.modules.evaluation.cli --provider mock --min-safety-recall 0.95

# View the generated report
cat reports/eval_*.md
```

### Step 10: Verify Audit Trail (~30 sec)

```bash
# Login as auditor
AUDITOR_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "auditor@demo.municipal.gov", "password": "AuditorDemo123!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Verify the entire audit hash chain
curl -s http://localhost:8000/api/v1/audit/verify \
  -H "Authorization: Bearer $AUDITOR_TOKEN" | python -m json.tool
```

---

## Testing

```bash
# Run all tests (75 tests)
make test
# Or: python -m pytest tests/ -v

# Run specific test modules
python -m pytest tests/integration/test_part10_hardening.py -v
python -m pytest tests/integration/test_part7_resolution_and_challenges.py -v

# Run with coverage
python -m pytest tests/ --cov=app --cov-report=html
```

### Test Categories

| Category | Count | Coverage |
|:---|:---:|:---|
| Identity & Auth | 9 | Registration, login, refresh, RBAC |
| Complaints & Attachments | 8 | Submission, geo, idempotency, upload security |
| AI Assist & Guardrails | 9 | Pipeline, PII, injection, kill switch, fallback |
| Routing & Priority & Duplicates | 6 | Rules, safety invariant, ranking, citizen similar |
| Cases & Activity | 6 | State machine, transitions, immutability, timeline |
| Resolution & Challenges | 7 | Evidence closure, self-review block, reopen, SLA |
| Chaos & Manual Triage | 6 | AI down, garbage, worker kill, notification failure |
| Evaluation Harness | 4 | Dataset, runner, thresholds, RBAC |
| Shared Infrastructure | 8 | Outbox, audit chain, idempotency, pagination |
| **Part 10 Hardening** | **8** | **RBAC route iteration, secrets audit, upload, CORS** |
| Health & Unit | 6 | Probes, request-id, Argon2, JWT |

---

## Evaluation Harness

```bash
# Run with mock provider (no API key needed)
make eval

# Run with Gemini (requires GEMINI_API_KEY in .env)
python -m app.modules.evaluation.cli --provider gemini

# Side-by-side comparison
python -m app.modules.evaluation.cli --compare

# CI mode: fail if safety recall drops below 95%
python -m app.modules.evaluation.cli --provider mock --min-safety-recall 0.95
```

### Benchmark Dataset: 215 ground-truth complaints
- **Multilingual**: English (70), Hindi (59), Kannada (53), Code-Mixed (33)
- **Safety-critical**: 50 high-hazard samples (live wires, gas leaks, open manholes)
- **Edge cases**: 15 vague/adversarial, 15 prompt injection attempts
- **Duplicate clusters**: 10 groups / 30 co-occurring complaints

---

## API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: [docs/openapi.json](docs/openapi.json) (62 paths, auto-generated)

Regenerate the OpenAPI spec:
```bash
python scripts/generate_openapi.py
```

---

## Architecture Decision Records

| # | Decision | Status |
|:---|:---|:---|
| [001](docs/adr/001-modular-monolith.md) | Modular monolith architecture | Accepted |
| [002](docs/adr/002-transactional-outbox.md) | Transactional outbox pattern | Accepted |
| [003](docs/adr/003-pgvector-duplicate-detection.md) | pgvector for duplicate detection | Accepted |
| [004](docs/adr/004-hash-chain-audit.md) | SHA-256 hash-chain audit trail | Accepted |
| [005](docs/adr/005-provider-abstraction.md) | AI provider abstraction & fail-safe | Accepted |
| [006](docs/adr/006-state-machine.md) | Central case state machine | Accepted |

---

## Known Gaps & Future Work

| Gap | Severity | Notes |
|:---|:---|:---|
| **No real PostgreSQL in CI** | Medium | Tests use SQLite in-memory; some PostGIS/pgvector features untested |
| **Rate limiter untested in CI** | Low | Requires Redis; gracefully degrades to allow-all in tests |
| **No email/SMS notification channels** | Medium | Only `ConsoleNotificationChannel` implemented; pluggable interface ready |
| **No file-size enforcement in middleware** | Low | Upload size validated in service layer; no nginx/reverse-proxy limit |
| **Mypy `ignore_missing_imports`** | Low | Some third-party stubs missing; strict mode for app code only |
| **No pagination on some list endpoints** | Low | Routing rules, priority policies return full lists |
| **No WebSocket real-time updates** | Medium | Citizen timeline is polling-based |
| **Embedding model is fixed** | Low | No A/B testing of embedding models in duplicate detection |
| **No multi-tenant support** | Low | Single municipality assumption; multi-tenant would need schema changes |
| **Circuit breaker state is in-memory** | Low | Resets on process restart; Redis-backed CB would be more resilient |
