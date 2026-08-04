"""HarborIQ v2 application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.middleware import PrometheusMiddleware, RequestIDMiddleware
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

app.include_router(api_router)


@app.get("/")
def root():
    return {"name": "HarborIQ", "version": "0.1.0", "docs": "/docs"}


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint (text exposition format).

    Deliberately unauthenticated — this is standard practice for Prometheus
    scraping (Prometheus itself has no bearer-token story for scrape
    targets by default) and the metrics here carry no tenant data, only
    aggregate request counts/latencies. In a real deployment this endpoint
    should still be firewalled to the scraper's network only rather than
    left open on the public internet; that is a reverse-proxy/network
    concern outside this app's control — see `docs/DEPLOYMENT.md`.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
