"""HTTP middleware: rate limiting, cache headers and basic hardening."""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

API_PREFIXES = ("/api/", "/mf", "/nav/", "/fund-houses", "/categories", "/stats", "/health")
EXEMPT_PREFIXES = ("/api/docs", "/api/redoc", "/api/openapi.json", "/assets", "/docs", "/health")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_api(path: str) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in API_PREFIXES)


def _is_exempt(path: str) -> bool:
    if path.endswith("/health"):
        return True
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-process sliding-window limiter (per client IP)."""

    def __init__(self, app, *, limit: int = 120, window: int = 60):
        super().__init__(app)
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if self.limit <= 0 or not _is_api(path) or _is_exempt(path):
            return await call_next(request)

        now = time.monotonic()
        key = _client_ip(request)
        bucket = self.hits[key]
        while bucket and bucket[0] <= now - self.window:
            bucket.popleft()

        if len(bucket) >= self.limit:
            retry_after = max(1, int(self.window - (now - bucket[0])) + 1)
            return JSONResponse(
                status_code=429,
                content={
                    "status": "RATE_LIMITED",
                    "message": (
                        f"Rate limit exceeded ({self.limit} requests per "
                        f"{self.window}s). Please retry in {retry_after}s."
                    ),
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        bucket.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.limit - len(bucket)))
        return response


class CacheHeadersMiddleware(BaseHTTPMiddleware):
    """Attach sensible public cache durations to API responses."""

    def __init__(self, app, *, default_ttl: int = 300):
        super().__init__(app)
        self.default_ttl = default_ttl

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        path = request.url.path
        if request.method == "GET" and response.status_code == 200:
            if "/latest" in path:
                ttl = 60
            elif path.endswith(("/stats", "/health", "/meta.json")):
                ttl = 60
            elif _is_api(path):
                ttl = self.default_ttl
            else:
                ttl = 3600
            response.headers.setdefault("Cache-Control", f"public, max-age={ttl}")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


def rate_limit_response(retry_after: int, limit: int, window: int) -> Response:
    """Kept for tests / custom integrations."""

    return JSONResponse(
        status_code=429,
        content=json.dumps(
            {
                "status": "RATE_LIMITED",
                "message": (
                    f"Rate limit exceeded ({limit} requests per {window}s). "
                    f"Please retry in {retry_after}s."
                ),
            }
        ),
        headers={"Retry-After": str(retry_after)},
    )
