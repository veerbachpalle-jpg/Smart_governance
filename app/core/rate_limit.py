"""
Redis-backed sliding-window rate limiter.

Gracefully degrades to allow-all when Redis is unreachable (dev/test).
Production deployments MUST have Redis available.
"""

import logging
import time
from typing import Any, Optional

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings

logger = logging.getLogger("app.core.rate_limit")

# ---------------------------------------------------------------------------
# Default rate-limit tiers (requests / window_seconds)
# ---------------------------------------------------------------------------
RATE_LIMIT_TIERS: dict[str, tuple[int, int]] = {
    # auth endpoints get tighter limits to deter brute-force
    "/api/v1/auth/login": (10, 60),  # 10 req / 60s per IP
    "/api/v1/auth/register": (5, 60),  # 5 req / 60s per IP
    "/api/v1/auth/refresh": (20, 60),  # 20 req / 60s per IP
    # upload endpoints
    "/api/v1/complaints/attachments/upload": (15, 60),
    # chaos & admin
    "/api/v1/admin/chaos": (10, 60),
    # default for everything else
    "__default__": (60, 60),  # 60 req / 60s per IP
}


def _get_limit(path: str) -> tuple[int, int]:
    """Return (max_requests, window_seconds) for a given path."""
    for prefix, limits in RATE_LIMIT_TIERS.items():
        if prefix != "__default__" and path.startswith(prefix):
            return limits
    return RATE_LIMIT_TIERS["__default__"]


def _client_key(request: Request) -> str:
    """Build a rate-limit key from client IP + path prefix."""
    forwarded = request.headers.get("X-Forwarded-For")
    client_ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    # Normalise path to the first 3 segments for grouping
    parts = request.url.path.rstrip("/").split("/")
    path_key = "/".join(parts[:5]) if len(parts) >= 5 else request.url.path
    return f"rl:{client_ip}:{path_key}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter backed by Redis sorted sets.

    Falls back to allow-all if Redis is unavailable so that
    local development and test suites are never blocked.
    """

    _redis: Optional[Any] = None
    _redis_checked: bool = False

    async def _get_redis(self) -> Optional[Any]:
        """Lazy-connect to Redis; cache the connection."""
        if self._redis_checked:
            return self._redis
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            # Smoke-test connection
            await self._redis.ping()
            logger.info("Rate limiter connected to Redis at %s", settings.REDIS_URL)
        except Exception:
            logger.warning(
                "Redis unavailable for rate limiting – falling back to allow-all. "
                "Set REDIS_URL to enable rate limiting."
            )
            self._redis = None
        finally:
            self._redis_checked = True
        return self._redis

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health probes
        if request.url.path in ("/health", "/ready", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        redis = await self._get_redis()
        if redis is None:
            # No Redis → allow request through
            return await call_next(request)

        max_requests, window = _get_limit(request.url.path)
        key = _client_key(request)
        now = time.time()

        try:
            pipe = redis.pipeline()
            # Remove entries older than the window
            pipe.zremrangebyscore(key, 0, now - window)
            # Add current request timestamp
            pipe.zadd(key, {str(now): now})
            # Count requests in window
            pipe.zcard(key)
            # Set TTL so keys auto-expire
            pipe.expire(key, window + 1)
            results = await pipe.execute()
            request_count: int = results[2]
        except Exception:
            # Redis error → allow through
            logger.debug("Redis error in rate limiter – allowing request through")
            return await call_next(request)

        if request_count > max_requests:
            retry_after = int(
                window - (now - float(list((await redis.zrange(key, 0, 0)) or [str(now)])[0]))
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "type": "https://api.grievance.gov/errors/rate-limit-exceeded",
                    "title": "Too Many Requests",
                    "status": 429,
                    "detail": f"Rate limit exceeded. Max {max_requests} requests per {window}s.",
                    "instance": request.url.path,
                    "code": "RATE_LIMIT_EXCEEDED",
                    "errors": [],
                },
                headers={
                    "Retry-After": str(max(retry_after, 1)),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, max_requests - request_count))
        return response
