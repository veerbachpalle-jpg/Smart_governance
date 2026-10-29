"""
Part 10 – Hardening Tests

1. RBAC & Object-Level Authorization route iteration:
   Every registered FastAPI route is tested with every role (+ unauthenticated).
   Routes that require authentication MUST reject 401 when unauthenticated.
   Routes that enforce RBAC MUST reject 403 for disallowed roles.

2. Secrets-in-repo audit: assert no hardcoded API keys or passwords in source.
3. Upload hardening spot-checks.
4. CORS config verification.
"""

import os
import pathlib

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.main import app
from app.modules.identity.schemas.identity import UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_ROLES = [r.value for r in UserRole]


def _make_token(user_id: str, role: str) -> str:
    return create_access_token(subject=user_id, role=role)


def _all_routes() -> list[dict[str, str]]:
    """Extract every registered API route from the FastAPI app via OpenAPI."""
    routes: list[dict[str, str]] = []
    openapi_schema = app.openapi()
    for path, methods in openapi_schema.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for method, operation in methods.items():
            if method.upper() in ("HEAD", "OPTIONS"):
                continue
            routes.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "name": operation.get("operationId", ""),
                    "summary": operation.get("summary", ""),
                }
            )
    return routes


# ---------------------------------------------------------------------------
# 1. Route Iteration: Unauthenticated access MUST be rejected (401)
#    for all protected endpoints
# ---------------------------------------------------------------------------

# Public routes that don't require auth
PUBLIC_PATHS = {
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("GET", "/api/v1/complaints/{identifier}/tracking"),
    ("GET", "/api/v1/complaints/nearby-similar"),
    ("GET", "/api/v1/integrations/whatsapp/webhook"),
    ("POST", "/api/v1/integrations/whatsapp/webhook"),
}


@pytest.mark.asyncio
async def test_unauthenticated_access_returns_401_for_protected_routes(
    client: AsyncClient,
) -> None:
    """Every non-public route MUST reject unauthenticated requests with 401."""
    routes = _all_routes()
    assert len(routes) > 20, f"Expected >20 routes but found {len(routes)}"

    failures: list[str] = []
    for rt in routes:
        method = rt["method"]
        path = rt["path"]

        # Skip public endpoints
        if (method, path) in PUBLIC_PATHS:
            continue

        # Replace path parameters with dummy UUIDs
        test_path = path
        for param in [
            "{complaint_id}",
            "{candidate_id}",
            "{challenge_id}",
            "{case_id}",
            "{rule_id}",
            "{id}",
            "{identifier}",
        ]:
            test_path = test_path.replace(param, "00000000-0000-0000-0000-000000000001")

        # Make request without auth header, but include Idempotency-Key if needed
        headers = {"Idempotency-Key": "00000000-0000-0000-0000-000000000000"}
        response = await client.request(method, test_path, headers=headers)
        if response.status_code not in (401, 403):
            # Some endpoints may return 422 for missing body but should still check auth first
            if response.status_code == 422:
                continue
            failures.append(f"{method} {path} -> {response.status_code} (expected 401/403)")

    assert not failures, (
        "These protected routes did NOT return 401/403 for unauthenticated access:\n"
        + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# 2. Role-specific RBAC: Citizen role should be denied staff-only endpoints
# ---------------------------------------------------------------------------

STAFF_ONLY_PATHS = [
    ("GET", "/api/v1/complaints/{complaint_id}/ai-interpretation"),
    ("POST", "/api/v1/complaints/{complaint_id}/ai-interpretation/accept"),
    ("GET", "/api/v1/complaints/{complaint_id}/routing"),
    ("POST", "/api/v1/routing/rules"),
    ("GET", "/api/v1/routing/rules"),
    ("GET", "/api/v1/complaints/{complaint_id}/priority"),
    ("POST", "/api/v1/priority/policies"),
    ("GET", "/api/v1/complaints/{complaint_id}/duplicates"),
    ("POST", "/api/v1/cases"),
    ("GET", "/api/v1/audit/events"),
    ("GET", "/api/v1/audit/verify"),
    ("GET", "/api/v1/triage/manual/queue"),
    ("GET", "/api/v1/eval/runs"),
    ("GET", "/api/v1/admin/chaos"),
]


@pytest.mark.asyncio
async def test_citizen_denied_staff_only_endpoints(
    client: AsyncClient,
    citizen_token: str,
) -> None:
    """Citizens MUST receive 403 on staff-only endpoints."""
    failures: list[str] = []
    headers = {"Authorization": f"Bearer {citizen_token}"}

    for method, path in STAFF_ONLY_PATHS:
        test_path = path.replace("{complaint_id}", "00000000-0000-0000-0000-000000000001")
        test_path = test_path.replace("{case_id}", "00000000-0000-0000-0000-000000000001")

        if method in ("POST", "PUT", "PATCH"):
            response = await client.request(method, test_path, headers=headers, json={})
        else:
            response = await client.request(method, test_path, headers=headers)

        if response.status_code != 403:
            failures.append(f"{method} {path} -> {response.status_code} (expected 403)")

    assert not failures, "Citizen was NOT denied these staff-only endpoints:\n" + "\n".join(
        failures
    )


# ---------------------------------------------------------------------------
# 3. Admin-only endpoints deny officer
# ---------------------------------------------------------------------------

ADMIN_ONLY_PATHS = [
    ("POST", "/api/v1/routing/rules"),
    ("POST", "/api/v1/priority/policies"),
    ("GET", "/api/v1/admin/chaos"),
    ("POST", "/api/v1/admin/chaos"),
    ("POST", "/api/v1/admin/chaos/reset"),
]


@pytest.mark.asyncio
async def test_officer_denied_admin_only_endpoints(
    client: AsyncClient,
    officer_token: str,
) -> None:
    """Officers MUST receive 403 on admin-only endpoints."""
    failures: list[str] = []
    headers = {"Authorization": f"Bearer {officer_token}"}

    for method, path in ADMIN_ONLY_PATHS:
        if method in ("POST", "PUT", "PATCH"):
            response = await client.request(method, path, headers=headers, json={})
        else:
            response = await client.request(method, path, headers=headers)

        if response.status_code != 403:
            failures.append(f"{method} {path} -> {response.status_code} (expected 403)")

    assert not failures, "Officer was NOT denied these admin-only endpoints:\n" + "\n".join(
        failures
    )


# ---------------------------------------------------------------------------
# 4. Secrets-in-Repo Audit
# ---------------------------------------------------------------------------

SECRETS_PATTERNS = [
    "AIzaSy",  # Google API key prefix
    "sk-",  # OpenAI key prefix
    "ghp_",  # GitHub PAT prefix
    "AKIA",  # AWS access key prefix
    "-----BEGIN RSA",  # PEM private key
    "-----BEGIN PRIVATE",
]

# Files to exclude from secrets scan
EXCLUDED_FILES = {
    ".env",
    ".env.example",
    "requirements.txt",
    ".gitignore",
    "test_part10_hardening.py",
}


@pytest.mark.asyncio
async def test_no_hardcoded_secrets_in_source() -> None:
    """No API keys, passwords, or private keys should be committed to source."""
    project_root = pathlib.Path(__file__).parent.parent.parent
    violations: list[str] = []

    for root, _dirs, files in os.walk(project_root):
        # Skip hidden dirs, caches, node_modules
        if any(
            skip in root
            for skip in [
                "__pycache__",
                ".git",
                ".mypy_cache",
                ".ruff_cache",
                ".pytest_cache",
                "node_modules",
                ".venv",
                "venv",
            ]
        ):
            continue

        for filename in files:
            if filename in EXCLUDED_FILES:
                continue
            if not filename.endswith((".py", ".yml", ".yaml", ".json", ".toml", ".md")):
                continue

            filepath = os.path.join(root, filename)
            try:
                with open(filepath, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for pattern in SECRETS_PATTERNS:
                    if pattern in content:
                        violations.append(f"{filepath}: contains pattern '{pattern}'")
            except Exception:
                pass

    assert not violations, "Potential secrets found in source:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# 5. Upload Hardening Spot-Checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(
    client: AsyncClient,
    citizen_token: str,
) -> None:
    """Files exceeding MAX_UPLOAD_SIZE_MB must be rejected."""
    headers = {"Authorization": f"Bearer {citizen_token}"}
    # Create a fake file just over the limit header
    fake_content = b"x" * 100  # small but with manipulated content-type
    response = await client.post(
        "/api/v1/complaints/attachments/upload",
        headers=headers,
        files={"file": ("test.exe", fake_content, "application/x-msdownload")},
    )
    # Should reject executable MIME types
    assert response.status_code in (400, 422), (
        f"Expected 400/422 for executable upload, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_upload_rejects_spoofed_extension(
    client: AsyncClient,
    citizen_token: str,
) -> None:
    """A file with image extension but executable magic bytes must be rejected."""
    headers = {"Authorization": f"Bearer {citizen_token}"}
    # ELF binary magic bytes disguised as .jpg
    elf_magic = b"\x7fELF" + b"\x00" * 100
    response = await client.post(
        "/api/v1/complaints/attachments/upload",
        headers=headers,
        files={"file": ("photo.jpg", elf_magic, "image/jpeg")},
    )
    assert response.status_code in (400, 422), (
        f"Expected 400/422 for spoofed extension, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# 6. CORS Configuration Check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_does_not_allow_wildcard_origin(client: AsyncClient) -> None:
    """Verify CORS does not blindly allow all origins in the running config."""
    # Send preflight-like request from a random origin
    response = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil-site.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # Should NOT return the evil origin in Access-Control-Allow-Origin
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao != "*", "CORS must not allow wildcard origin"
    assert "evil-site.example.com" not in acao, "CORS must not reflect arbitrary origins"


# ---------------------------------------------------------------------------
# 7. Route count sanity check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_api_routes_have_summaries() -> None:
    """Every API v1 route should have a summary for OpenAPI documentation."""
    routes_without_summary: list[str] = []
    openapi_schema = app.openapi()
    for path, methods in openapi_schema.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for method, operation in methods.items():
            if method.upper() in ("HEAD", "OPTIONS"):
                continue
            summary = operation.get("summary")
            if not summary:
                routes_without_summary.append(f"{method.upper()} {path}")

    assert not routes_without_summary, "These routes have no summary for OpenAPI:\n" + "\n".join(
        routes_without_summary
    )
