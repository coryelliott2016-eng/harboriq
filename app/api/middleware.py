"""Cross-cutting ASGI middleware: request-id correlation and Prometheus metrics.

Both middlewares are deliberately dependency-free of the route layer (they
wrap every request at the ASGI level via Starlette's BaseHTTPMiddleware) so
adding a new route never has to remember to opt in.
"""
from __future__ import annotations

import time
import uuid

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.core.config import settings

REQUEST_ID_HEADER = "X-Request-ID"

log = structlog.get_logger()

# --- Prometheus metrics ---------------------------------------------------
# Labelled by method/path/status. `path` uses the *route template*
# (e.g. "/api/v1/jobs/{id}"), not the raw URL, so per-tenant/per-id traffic
# does not explode the metric's cardinality — see `_route_label` below.
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path", "status"],
)


def _route_label(request: Request) -> str:
    """Best-effort route template for metric labels.

    Starlette only populates `request.scope["route"]` once routing has
    resolved (i.e. after `call_next` returns), so this must be read after
    the downstream handler runs. Unmatched paths (404s) fall back to the
    raw path — bounded in practice since there is no user-controlled path
    segment that isn't itself templated.
    """
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return request.url.path


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign (or propagate) a request id and bind it into structlog context.

    - If the inbound request already carries `X-Request-ID` (typically set
      by a reverse proxy / load balancer upstream of this app), that value
      is reused verbatim so a single request keeps one id end to end.
    - Otherwise a fresh UUID4 is generated.
    - The id is bound into `structlog.contextvars` for the lifetime of the
      request, so every log line emitted while handling it — from any
      module, without threading the value through function signatures —
      carries `request_id` automatically.
    - The id is always echoed back as the `X-Request-ID` response header,
      so a caller (or the proxy) can correlate a specific response with the
      server-side logs for it.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else str(uuid.uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline HTTP security response headers (Security Core Prompt v1.0,
    H-3 fix; OWASP ASVS V14 "HTTP Security Headers").

    This is a pure API backend (the SPA is served separately by nginx, which
    gets its own copy of these headers — see `frontend/nginx.conf`), so the
    policy here is deliberately strict and has none of a traditional
    server-rendered site's inline-script/style needs:

    - `Strict-Transport-Security`: only sent once `app_env` is not
      `development`, so a local plain-HTTP dev server is never told by the
      browser to upgrade every future request to HTTPS (which would break
      it). `includeSubDomains` + a 1-year max-age is the standard
      preload-eligible baseline; `preload` itself is intentionally left out
      since submitting to the HSTS preload list is a one-way, cross-team
      decision that shouldn't be made implicitly by this middleware.
    - `Content-Security-Policy`: `default-src 'none'` — this origin never
      serves HTML/JS/images itself (JSON API only), so there is nothing to
      allow-list. `frame-ancestors 'none'` blocks this API from being
      framed anywhere (defense-in-depth alongside `X-Frame-Options`).
    - `X-Content-Type-Options: nosniff` — stops browsers from MIME-sniffing
      JSON responses (or user-uploaded attachment bytes, see M-3) as HTML.
    - `X-Frame-Options: DENY` and `Referrer-Policy: strict-origin-when-
      cross-origin` — standard clickjacking / referrer-leak hardening.
    - `Permissions-Policy` — explicitly denies browser features this API
      has no reason to grant.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    # Swagger UI / ReDoc render actual HTML in the browser and pull their
    # JS/CSS from a CDN, so the `default-src 'none'` API policy below would
    # break them outright. They're documentation surfaces, not the JSON API
    # surface this policy protects, so they get a separate, docs-appropriate
    # CSP instead of being silently broken.
    _DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=(), payment=()"
        )
        if request.url.path in self._DOCS_PATHS:
            headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data: fastapi.tiangolo.com; "
                "script-src 'self' cdn.jsdelivr.net 'unsafe-inline'; "
                "style-src 'self' cdn.jsdelivr.net 'unsafe-inline'; "
                "frame-ancestors 'none'"
            )
        else:
            headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )
        if settings.app_env != "development":
            headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record request count + latency for every request, labelled by route.

    Deliberately does not special-case `/metrics` itself — scraping the
    scraper endpoint is cheap and consistent, and excluding it would just be
    one more special case to maintain for no real benefit.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            path = _route_label(request)
            labels = {
                "method": request.method,
                "path": path,
                "status": str(status_code),
            }
            REQUEST_COUNT.labels(**labels).inc()
            REQUEST_LATENCY.labels(**labels).observe(duration)
