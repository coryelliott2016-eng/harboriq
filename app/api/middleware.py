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
