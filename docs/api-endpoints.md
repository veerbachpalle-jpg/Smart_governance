# Municipal Grievance System - API Endpoints Specification

All endpoints are versioned under `/api/v1`.
All mutating endpoints (`POST`, `PUT`, `PATCH`) support the `Idempotency-Key` HTTP header.
All listing endpoints use cursor pagination (`?limit=20&cursor=...`).

---

## 1. Identity & Access Management (`identity`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | `public` | Register a new citizen account with phone/email and password. |
| `POST` | `/api/v1/auth/login` | `public` | Authenticate user credentials and return JWT access and refresh tokens. |
| `POST` | `/api/v1/auth/refresh` | `public` | Exchange a valid refresh token for a new access token. |
| `GET` | `/api/v1/users/me` | `authenticated` | Retrieve current user profile and role claims. |
| `PATCH` | `/api/v1/users/me/profile` | `citizen`, `officer` | Update personal profile details and notification preferences. |
| `GET` | `/api/v1/users` | `admin`, `supervisor` | List users with filtering by role, department, or active status. |
| `POST` | `/api/v1/users` | `admin` | Create officer, supervisor, or auditor user accounts. |
| `GET` | `/api/v1/departments` | `authenticated` | List all municipal departments and their active codes. |
| `POST` | `/api/v1/departments` | `admin` | Create a new municipal department entity. |
| `GET` | `/api/v1/departments/{id}/members` | `admin`, `supervisor`, `department_lead` | List officers and leads assigned to a department. |
| `POST` | `/api/v1/departments/{id}/members` | `admin`, `supervisor` | Assign a user to a department with a specific role. |

---

## 2. Complaints Management (`complaints`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/complaints` | `citizen` | Submit a new municipal complaint with geo-coordinates and details. |
| `GET` | `/api/v1/complaints` | `citizen` (own), `officer`, `department_lead`, `supervisor`, `auditor` | Cursor-paginated list of complaints filtered by status, ward, or date. |
| `GET` | `/api/v1/complaints/{id}` | `citizen` (own), `officer`, `department_lead`, `supervisor`, `auditor` | Retrieve comprehensive complaint details and current status. |
| `POST` | `/api/v1/complaints/{id}/attachments` | `citizen` (own), `officer` | Upload photos or documents associated with the complaint. |
| `GET` | `/api/v1/complaints/{id}/attachments` | `citizen` (own), `officer`, `department_lead`, `supervisor`, `auditor` | List all media files and hashes attached to a complaint. |
| `POST` | `/api/v1/complaints/{id}/reject` | `officer`, `supervisor` | Reject an invalid or out-of-scope complaint with a mandatory reason. |

---

## 3. AI Assistance & Triage (`ai_assist`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/ai-assist/triage/{complaint_id}` | `officer`, `supervisor`, `admin` | Trigger asynchronous or manual fallback AI triage re-run. |
| `GET` | `/api/v1/ai-assist/triage/{complaint_id}` | `officer`, `department_lead`, `supervisor`, `auditor` | View AI categorization, summary, extracted factors, and confidence score. |
| `POST` | `/api/v1/ai-assist/triage/{complaint_id}/decide` | `officer`, `supervisor` | Human officer accepts, overrides, or rejects AI interpretation recommendations. |

---

## 4. Routing Intelligence (`routing`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/routing/rules` | `admin`, `supervisor`, `auditor` | List all versioned department routing rules and geospatial boundaries. |
| `POST` | `/api/v1/routing/rules` | `admin` | Create a new immutable version of a department routing rule. |
| `GET` | `/api/v1/routing/recommendations/{complaint_id}` | `officer`, `department_lead`, `supervisor`, `auditor` | View AI and rule-matched routing recommendations for a complaint. |
| `POST` | `/api/v1/routing/recommendations/{complaint_id}/decide` | `officer`, `supervisor` | Accept recommended department or provide human override with department ID and justification. |

---

## 5. Priority & SLA Assessment (`priority`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/priority/policies` | `admin`, `supervisor`, `auditor` | List priority evaluation policies, criteria matrices, and SLA targets. |
| `POST` | `/api/v1/priority/policies` | `admin` | Publish a new versioned priority policy matrix. |
| `GET` | `/api/v1/priority/assessments/{complaint_id}` | `officer`, `department_lead`, `supervisor`, `auditor` | View AI priority assessment, severity score, and detected risk factors. |
| `POST` | `/api/v1/priority/assessments/{complaint_id}/decide` | `officer`, `supervisor` | Human officer locks final priority (LOW/MEDIUM/HIGH/CRITICAL) or overrides AI. |

---

## 6. Duplicate Detection (`duplicates`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/duplicates/candidates/{complaint_id}` | `officer`, `supervisor`, `auditor` | List candidate duplicate complaints matching spatial, temporal, and semantic thresholds. |
| `POST` | `/api/v1/duplicates/decide` | `officer`, `supervisor` | Human decision to link complaint as duplicate of an existing parent case or reject similarity. |

---

## 7. Case Lifecycle & Ownership (`cases`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/cases` | `officer`, `department_lead`, `supervisor`, `auditor` | Cursor-paginated list of cases with multi-department, status, and SLA filters. |
| `GET` | `/api/v1/cases/{id}` | `citizen` (if owner), `officer`, `department_lead`, `supervisor`, `auditor` | Retrieve full case dossier including lead department, officer, and deadlines. |
| `POST` | `/api/v1/cases/{id}/accept-lead` | `department_lead` | Department lead formally accepts ownership of routed case. |
| `POST` | `/api/v1/cases/{id}/assign` | `department_lead`, `supervisor` | Assign a designated field officer to work on the case. |
| `POST` | `/api/v1/cases/{id}/request-reassign` | `department_lead`, `officer` | Request transfer of case accountability with mandatory jurisdictional reasoning. |
| `POST` | `/api/v1/cases/{id}/reassign` | `supervisor` | Reassign lead department accountability to another municipal unit. |

---

## 8. Case Activity & Citizen Communication (`activity`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/cases/{id}/activities` | `citizen` (CITIZEN_VISIBLE only), `officer`, `department_lead`, `supervisor`, `auditor` | Retrieve immutable chronological case activity log. |
| `POST` | `/api/v1/cases/{id}/activities` | `officer`, `department_lead`, `supervisor` | Record an operational note or progress milestone (flagged INTERNAL or CITIZEN_VISIBLE). |
| `POST` | `/api/v1/cases/{id}/citizen-updates` | `citizen` | Citizen provides additional situational information or comments on active case. |
| `GET` | `/api/v1/cases/{id}/citizen-updates` | `citizen` (own), `officer`, `department_lead`, `supervisor`, `auditor` | List citizen-submitted remarks and supplementary details. |

---

## 9. Resolution Proposals & Citizen Challenges (`challenges`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/cases/{id}/resolution/propose` | `officer`, `department_lead` | Propose case resolution with mandatory remediation proof photos and verification flag. |
| `GET` | `/api/v1/cases/{id}/resolution/proposal` | `citizen` (own), `officer`, `department_lead`, `supervisor`, `auditor` | View proposed resolution, remediation notes, officer sign-off, and review countdown. |
| `POST` | `/api/v1/cases/{id}/resolution/confirm` | `citizen` | Citizen explicitly confirms resolution satisfaction, immediately transitioning case to CLOSED. |
| `POST` | `/api/v1/cases/{id}/resolution/challenge` | `citizen` | Citizen disputes resolution within 7-day window with mandatory reason and counter-proof. |
| `GET` | `/api/v1/challenges` | `supervisor`, `auditor` | List unresolved citizen challenges pending supervisor escalation review. |
| `GET` | `/api/v1/challenges/{id}` | `citizen` (if owner), `supervisor`, `auditor` | View challenge dossier, citizen arguments, and proposed resolution proof. |
| `POST` | `/api/v1/challenges/{id}/review` | `supervisor` | Issue binding review verdict: UPHELD (reopens case to IN_PROGRESS) or OVERTURNED (closes case). |

---

## 10. Audit Trail & Governance (`audit`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/audit/events` | `auditor`, `admin` | Search tamper-evident audit logs by entity type, entity ID, actor, or date range. |
| `GET` | `/api/v1/audit/events/{id}` | `auditor`, `admin` | Inspect individual audit record including actor role, IP address, and JSON state diff. |

---

## 11. Notifications (`notifications`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/notifications` | `authenticated` | List in-app notifications for the calling user with unread filter. |
| `POST` | `/api/v1/notifications/{id}/read` | `authenticated` | Mark a specific user notification as read. |
| `POST` | `/api/v1/notifications/read-all` | `authenticated` | Mark all unread notifications as read for current user. |

---

## 12. AI Evaluation Harness (`evaluation`)

| Method | Path | Allowed Roles | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/evaluations/datasets` | `admin`, `auditor` | List benchmark evaluation datasets for categorization, routing, and duplicate tasks. |
| `POST` | `/api/v1/evaluations/datasets` | `admin` | Upload and register a new ground-truth benchmark dataset. |
| `POST` | `/api/v1/evaluations/runs` | `admin` | Execute an evaluation run across a benchmark dataset for a given model or prompt version. |
| `GET` | `/api/v1/evaluations/runs` | `admin`, `auditor` | List all historical evaluation runs and execution status. |
| `GET` | `/api/v1/evaluations/runs/{id}` | `admin`, `auditor` | Fetch comprehensive run metrics (Accuracy, Precision, Recall, F1, Latency, Confusion Matrix). |
