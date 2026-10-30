import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppException
from app.core.logging import setup_logging
from app.core.middleware import (
    RequestIdMiddleware,
    app_exception_handler,
    generic_exception_handler,
    validation_exception_handler,
)
from app.db.session import engine, get_db
from app.modules.activity.api import activity_router
from app.modules.admin.api import chaos_router
from app.modules.ai_assist.api import ai_router, triage_router
from app.modules.ai_assist.service import setup_ai_assist_handlers
from app.modules.audit.api import audit_router
from app.modules.cases.api import cases_router
from app.modules.challenges.api import challenges_router
from app.modules.complaints.api import complaints_router
from app.modules.duplicates.api import duplicates_router
from app.modules.evaluation.api import evaluation_router
from app.modules.identity.api import auth_router, users_router
from app.modules.integrations.whatsapp.router import whatsapp_router
from app.modules.priority.api import priority_router
from app.modules.routing.api import routing_router

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging(settings.LOG_LEVEL)
    logger.info("Starting up Grievance Intelligence API (%s)", settings.ENVIRONMENT)
    setup_ai_assist_handlers()
    yield
    logger.info("Shutting down Grievance Intelligence API")
    await engine.dispose()


app = FastAPI(
    title="AI-Powered Municipal Grievance Intelligence & Accountability System",
    description="Backend API for intelligent grievance triage, routing, and evidence-verified resolution.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Middleware (order matters: outermost first)
# Rate limiting (Redis-backed, graceful degradation in dev/test)
if settings.RATE_LIMIT_ENABLED:
    from app.core.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware)

# CORS: Configurable origins; defaults to localhost dev URLs.
# In production, set CORS_ORIGINS env var to the specific frontend domain.
_cors_origins: list[str] = [
    origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)
app.add_middleware(RequestIdMiddleware)

# Exception handlers for RFC 7807 compliance
app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, generic_exception_handler)


# Health & Readiness Probes
@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    tags=["System"],
    summary="Liveness probe",
)
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "grievance-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    tags=["System"],
    summary="Readiness probe verifying database connectivity",
)
async def readiness_check(session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "database": "connected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Mount API v1 Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(duplicates_router, prefix="/api/v1")
app.include_router(complaints_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(routing_router, prefix="/api/v1")
app.include_router(priority_router, prefix="/api/v1")
app.include_router(activity_router, prefix="/api/v1")
app.include_router(cases_router, prefix="/api/v1")
app.include_router(challenges_router, prefix="/api/v1")
app.include_router(triage_router, prefix="/api/v1")
app.include_router(chaos_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")
app.include_router(whatsapp_router, prefix="/api/v1")
