from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        is_production = settings.ENVIRONMENT.lower() == "production"

        # Headers to set if not already present on response
        headers_to_set: dict[str, tuple[str, str]] = {
            "x-content-type-options": ("X-Content-Type-Options", "nosniff"),
            "x-frame-options": ("X-Frame-Options", "DENY"),
            "referrer-policy": ("Referrer-Policy", "strict-origin-when-cross-origin"),
            "permissions-policy": (
                "Permissions-Policy",
                "camera=(), microphone=(), geolocation=()",
            ),
            "cross-origin-opener-policy": ("Cross-Origin-Opener-Policy", "same-origin"),
        }

        if is_production:
            headers_to_set["strict-transport-security"] = (
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        # Skip CSP for docs/redoc/openapi.json
        req_path = request.url.path
        if req_path not in DOCS_PATHS and not any(req_path.startswith(dp) for dp in DOCS_PATHS):
            headers_to_set["content-security-policy"] = (
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            )

        # Do not override a header if the route already set it
        for lower_key, (header_name, header_value) in headers_to_set.items():
            if lower_key not in response.headers:
                response.headers[header_name] = header_value

        return response
