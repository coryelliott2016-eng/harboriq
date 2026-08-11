"""HarborIQ v2 application entrypoint."""
import secrets

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.middleware import (
    PrometheusMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.observability import init_sentry

configure_logging()
init_sentry()

app = FastAPI(
    title="HarborIQ",
    version="0.1.0",
    description="Marine service operating system (corrected scaffold).",
)

# The React frontend (Phase 4) is served from a different origin (the Vite
# dev server at :5173 in development; a separate nginx container in prod),
# so the browser enforces CORS on every API call it makes. Origins are
# configurable via CORS_ALLOW_ORIGINS (comma-separated) so each deployment
# can allowlist only the origins it actually serves the frontend from.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware runs outermost-added-last (Starlette wraps in reverse
# registration order), so RequestIDMiddleware — which every log line during
# the request should carry — is added last so its contextvars binding wraps
# the Prometheus timing and every route handler underneath it.
app.add_middleware(PrometheusMiddleware)
app.add_middleware(RequestIDMiddleware)
# Added last so it wraps everything (including error responses) and is the
# final thing to touch headers before the response leaves the app.
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(api_router)


@app.get("/")
def root():
    return {"name": "HarborIQ", "version": "0.1.0", "docs": "/docs"}


@app.get("/metrics")
def metrics(authorization: str | None = Header(default=None)):
    """Prometheus scrape endpoint (text exposition format).

    Carries no tenant data — only aggregate request counts/latencies — but
    still discloses route inventory and traffic shape, so it is gated by
    `METRICS_TOKEN` (Authorization: Bearer …) whenever that setting is
    non-empty. Outside development the process refuses to start without a
    token (see `Settings._require_metrics_token_outside_development`), so
    production scrapes always authenticate. In development an empty token
    keeps the historical open-scrape behaviour for local Prometheus.

    Network-layer restriction (reverse-proxy `remote_ip` / firewall) remains
    recommended as defense-in-depth — see `docs/DEPLOYMENT.md`.
    """
    expected = (settings.metrics_token or "").strip()
    if expected:
        provided = ""
        if authorization and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing metrics bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
