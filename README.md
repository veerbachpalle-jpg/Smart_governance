# Smart Governance

### AI-Assisted Municipal Grievance Intelligence and Accountability

**Live frontend demo:** https://smart-governance-woad.vercel.app/  
**API documentation (local):** http://localhost:8000/docs

> **Core principle: AI recommends; accountable people decide.**

Smart Governance is a municipal grievance management prototype designed to help citizens report local civic issues and help municipal teams triage, prioritise, route, coordinate, and review those reports. It combines a citizen-facing portal with a FastAPI backend, AI-assisted recommendations, case workflows, citizen challenges, and a tamper-evident audit trail.

> **Demo notice:** The hosted website is a frontend demonstration. Demo-mode complaints use sample data and are **not sent to a municipal authority**. Do not enter real personal or sensitive information into the demo.

## Contents

- [Problem](#problem)
- [What the project includes](#what-the-project-includes)
- [Human oversight and accountability](#human-oversight-and-accountability)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Repository structure](#repository-structure)
- [Run the application](#run-the-application)
- [Configuration](#configuration)
- [Demo accounts](#demo-accounts)
- [API overview](#api-overview)
- [Testing and code quality](#testing-and-code-quality)
- [Deployment](#deployment)
- [Current limitations](#current-limitations)
- [Roadmap](#roadmap)

## Problem

Municipal grievances can be difficult to manage when reports arrive in different formats, refer to the same incident, reach the wrong department, or have no clear owner. Citizens may also have limited visibility into what happened after submitting a complaint.

Smart Governance explores a more accountable workflow by combining structured complaint intake, decision support for staff, case ownership, public-facing updates, evidence-backed resolution proposals, and a way for citizens to challenge actions.

## What the project includes

### Citizen Portal

- Submit a civic issue with a title, description, category, location, and optional photos.
- Enter or select a location using the map and coordinates.
- Use browser-supported speech recognition for voice-to-text input.
- Browse complaint details, tracking information, and activity timelines.
- Review a proposed resolution and challenge an action when the issue has not been addressed.
- Explore the interface in a clearly labelled demonstration mode using sample records.

### Staff and Administration Workflows

- Role-based workflows for citizens, officers, department leads, supervisors, administrators, and auditors.
- AI-assisted complaint interpretation with structured fields, confidence, reported facts, and inferences.
- Department-routing and priority recommendations, with human accept, override, or reject decisions.
- Priority queue support for potentially safety-critical reports.
- Similar-incident suggestions using location, time, category, and semantic signals; staff can link or dismiss candidates rather than automatically merge them.
- Case grouping, participating departments, and a designated accountable lead department.
- Case activity entries that distinguish internal notes from citizen-visible updates.
- Resolution proposals with evidence and a citizen review/challenge workflow.
- Audit-event listing and hash-chain integrity verification.
- A manual-triage path when AI is unavailable or a recommendation cannot be safely used.

Feature availability differs between the interactive frontend demo and the backend API. The hosted demo should be treated as a product walkthrough, not a live municipal service.

## Human Oversight and Accountability

The backend is designed around the following safeguards:

1. **Recommendations are not decisions.** Routing, priority, and interpretation output is presented for staff review.
2. **Manual fallback.** The code includes a manual-triage route for cases that need human assessment.
3. **No automatic duplicate merging.** Similarity results are candidates for human review.
4. **Evidence-backed resolution.** Case workflows support resolution proposals and verification/review steps.
5. **Citizen recourse.** Citizens can challenge eligible actions; reviewer logic is designed to prevent self-review.
6. **Auditable changes.** The backend records audit events and exposes an endpoint to verify the hash chain.

These are prototype safeguards and should be reviewed, tested, and operationally validated before deployment in a real municipal environment.

## Architecture

The backend is organised as a modular monolith. API routers delegate business logic to service layers, with SQLAlchemy repositories and PostgreSQL persistence. Redis supports infrastructure features, MinIO is configured for object storage, and the AI layer supports a Gemini REST provider plus a deterministic mock provider.

```mermaid
flowchart TD
    Citizen[Citizen Portal] --> API[FastAPI API]
    Staff[Staff Console] --> API
    API --> Auth[Authentication and access control]
    API --> Modules[Complaint, AI, routing, priority, case, challenge and audit modules]
    Modules --> DB[(PostgreSQL / PostGIS)]
    Modules --> Redis[(Redis)]
    Modules --> Storage[(MinIO object storage)]
    Modules --> Outbox[(Transactional outbox)]
    Modules --> AI[AI provider abstraction]
    AI --> Gemini[Gemini REST provider]
    AI --> Mock[Deterministic mock provider]
```

The Docker Compose stack runs an ARQ worker for transactional outbox events, expired citizen-review windows, and challenge SLA checks. The Render prototype profile runs the API and worker under one supervisor process to stay within a single compute service; split them before horizontally scaling the API.

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React, TypeScript, Vite, TanStack Router, TanStack Query, Tailwind CSS, Leaflet |
| Backend API | Python 3.12, FastAPI, Pydantic v2, Uvicorn |
| Persistence | SQLAlchemy async, Alembic, PostgreSQL, PostGIS-capable Docker image |
| Infrastructure | Docker Compose, Redis, MinIO |
| Authentication | JWT access/refresh tokens, Argon2 password hashing, role-based access control |
| AI | Google Gemini REST API and deterministic `MockProvider` |
| Testing and quality | pytest, pytest-asyncio, httpx, Ruff, mypy, Vitest, ESLint |

## Repository Structure

```text
Smart_governance/
├── app/
│   ├── main.py                 # FastAPI app, middleware and API routers
│   ├── config.py               # Environment-based settings
│   ├── core/                   # Security, middleware, rate limiting, outbox and worker code
│   ├── db/                     # Database session, models base and seed data
│   └── modules/                # Feature modules (identity, complaints, AI, routing, etc.)
├── alembic/                    # Database migrations
├── docs/                       # Architecture, API endpoints, state machine and OpenAPI snapshot
├── frontend/                   # React/TypeScript web application
├── tests/                      # Unit and integration tests
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── make.bat
├── pyproject.toml
├── requirements.txt
└── .env.example
```

## Run the Application

### Prerequisites

- Docker Engine and Docker Compose
- Node.js and npm, if running the frontend locally
- Python 3.12 and pip, if running tests or backend tools directly on the host
- A Gemini API key only if you want to test the real Gemini provider; the backend falls back to `MockProvider` when no key is configured

### 1. Start the Backend and Its Dependencies

From the repository root:

```bash
git clone https://github.com/veerbachpalle-jpg/Smart_governance.git
cd Smart_governance
docker compose up --build -d
```

Apply the database migrations and load the development seed data:

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m app.db.seed
```

Open the API documentation at **http://localhost:8000/docs**.

Other useful endpoints are:

- `GET http://localhost:8000/health` — API liveness check
- `GET http://localhost:8000/ready` — database readiness check

View service logs with:

```bash
docker compose logs -f api
```

Stop the stack with:

```bash
docker compose down
```

The development database, Redis, and MinIO data are stored in Docker volumes. To remove those volumes as well, use `docker compose down -v`. This deletes local development data.

### 2. Run the Frontend Locally

In a second terminal:

```bash
cd frontend
npm install
cp .env.example .env.local
```

For a standalone walkthrough, set the following in `frontend/.env.local`:

```dotenv
VITE_USE_MOCKS=true
```

Then start the Vite development server:

```bash
npm run dev
```

Open the local URL printed by Vite, usually **http://localhost:5173**.

In demo mode, the portal uses sample records and does not submit reports to a municipal authority.

The frontend also contains an API client and an Original Mode switch. The end-to-end frontend/backend contract is not complete for every action; verify the request fields and endpoint paths before using Original Mode as a connected service. The backend API can be explored independently through `/docs`.

### 3. Run Backend Commands Directly (Optional)

Create and activate a Python 3.12 virtual environment, then install dependencies:

```bash
python -m venv .venv
```

On Linux/macOS:

```bash
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

For host-based backend development, ensure PostgreSQL, Redis, and MinIO are running and that the `.env` settings point to those services. Then run:

```bash
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Configuration

The root `.env.example` documents the main local settings. Important backend settings include:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Async SQLAlchemy database connection string |
| `REDIS_URL` | Redis connection string |
| `STORAGE_BACKEND`, `LOCAL_UPLOAD_DIR` | Attachment storage mode and local/persistent upload path |
| `MINIO_ENDPOINT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Reserved MinIO configuration; the current attachment implementation uses local storage |
| `JWT_SECRET_KEY` | JWT signing secret; replace the development value before deployment |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` | Token lifetimes |
| `AI_ENABLED` | Enables or disables AI-assisted processing |
| `GEMINI_API_KEY` | Optional key for the real Gemini provider; omit it to use the mock provider |
| `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL` | Gemini model names used by the provider |
| `AI_CONFIDENCE_THRESHOLD`, `AI_TIMEOUT_SECONDS` | AI confidence and timeout configuration |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `RATE_LIMIT_ENABLED` | Enables Redis-backed rate limiting |
| `MAX_UPLOAD_SIZE_MB` | Upload size limit |

The current Compose file uses development-oriented settings and credentials in its service definitions. Do not deploy it unchanged to production. Configure secrets, CORS, storage, database access, and the background worker for the target environment.

## Demo Accounts

Running the seed command creates development accounts. These credentials are for **local development only**:

| Role | Email | Password |
|---|---|---|
| Citizen | `citizen@example.com` | `CitizenDemo123!` |
| Officer | `officer@example.com` | `OfficerDemo123!` |
| Department lead | `lead@example.com` | `LeadDemo123!` |
| Supervisor | `supervisor@example.com` | `SupervisorDemo123!` |
| Administrator | `admin@example.com` | `AdminDemo123!` |
| Auditor | `auditor@example.com` | `AuditorDemo123!` |

Do not reuse these credentials or retain seeded accounts in a production environment. The hosted frontend demo uses its own sample mode; these backend accounts are not required to explore it.

## API Overview

The API is versioned under `/api/v1`. Interactive documentation and request schemas are available at `/docs` when the backend is running. A checked-in OpenAPI snapshot is available at [`docs/openapi.json`](docs/openapi.json).

| Area | Example endpoints | Purpose |
|---|---|---|
| Authentication | `POST /api/v1/auth/register`, `POST /api/v1/auth/login` | Citizen registration and token issuance |
| Complaints | `POST /api/v1/complaints`, `GET /api/v1/complaints/{complaint_id}` | Submit and retrieve complaints |
| AI interpretation | `GET /api/v1/complaints/{complaint_id}/ai-interpretation` | View a structured triage recommendation |
| Routing | `GET /api/v1/complaints/{complaint_id}/routing` | Inspect department suggestions |
| Priority | `GET /api/v1/complaints/{complaint_id}/priority`, `GET /api/v1/priority/queue` | Review priority assessments and safety queue |
| Similar incidents | `GET /api/v1/complaints/{complaint_id}/duplicates` | Retrieve duplicate candidates for staff review |
| Cases | `POST /api/v1/cases`, `POST /api/v1/cases/{case_id}/transition` | Group complaints and manage case state |
| Challenges | `POST /api/v1/cases/{case_id}/challenge`, `POST /api/v1/challenges/{challenge_id}/review` | Submit and review challenges |
| Audit | `GET /api/v1/audit/events`, `GET /api/v1/audit/verify` | Query audit history and verify the hash chain |
| Manual triage | `GET /api/v1/triage/manual/queue` | Find complaints awaiting human triage |

Creating complaint requests require an `Idempotency-Key` header. Authentication and role permissions apply to protected endpoints; consult the live API documentation for exact schemas and requirements.

## Testing and Code Quality

Install the Python dependencies before running the backend suite:

```bash
pip install -r requirements.txt
python -m pytest -q
```

Additional backend checks:

```bash
ruff check .
ruff format --check .
mypy app
```

Frontend checks (from `frontend/`):

```bash
npm test
npm run lint
npm run build
```

Tests should be run in the target development environment before submitting changes. The repository contains unit and integration tests; test results are not represented as passing unless the commands have been run successfully.

## Deployment

The checked-in [`render.yaml`](render.yaml) is a reproducible prototype backend deployment for Render. It provisions a FastAPI web service, PostgreSQL, and Redis-compatible Key Value in Singapore, runs Alembic before deployment, generates the JWT secret, and starts both the API and ARQ worker. Import the repository as a Render Blueprint, then verify `/health`, `/ready`, and `/docs`.

The frontend is connected to Vercel/Lovable from the `frontend/` root. For a connected live backend, configure these Vercel production variables and redeploy:

```dotenv
VITE_API_BASE_URL=https://<backend-host>/api/v1
VITE_USE_MOCKS=false
```

Keep `VITE_USE_MOCKS=true` for the public walkthrough until the backend URL, CORS origin, accounts, and data-retention policy have been validated. The frontend deliberately remains in demonstration mode when no API URL is configured.

The free Render profile is suitable only for a hackathon demonstration: services can sleep, Redis data is non-persistent, the free database is time-limited under Render's current terms, and local uploads are ephemeral unless a persistent disk or object-storage adapter is added.

## Current Limitations

- The hosted frontend is a demonstration with sample data, not a live government service.
- Live sign-in, complaint listing/submission, photo upload, public tracking, and support use backend-compatible contracts. Staff decisions, case transitions, resolution review, and challenges are still demo-only in the frontend even though backend endpoints exist.
- Attachment bytes use local filesystem storage. The prototype deployment needs a persistent disk or a completed object-storage adapter before uploads can be treated as durable.
- The single-service Render supervisor is a cost-saving prototype fallback. Use separate API and worker services before scaling beyond one API instance.
- Notification delivery and real municipal channels, such as official SMS, email, or government systems, require deployment-specific integration.
- Seed credentials, JWT defaults, and Compose service passwords are for local development only.
- No official municipal boundaries, municipal integrations, or production service-level commitments are configured in this repository.

## Roadmap

- Complete and test the frontend/backend API integration across all user workflows.
- Split the ARQ worker into a separately monitored service for production scaling.
- Add production secret management, deployment profiles, monitoring, and operational alerting.
- Integrate official municipal ward boundaries and department data.
- Add real notification channels and measure AI recommendation quality on appropriately governed, anonymised datasets.
- Conduct security, privacy, accessibility, and workflow testing with municipal stakeholders before any real-world rollout.
