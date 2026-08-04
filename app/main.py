"""HarborIQ v2 application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

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

app.include_router(api_router)


@app.get("/")
def root():
    return {"name": "HarborIQ", "version": "0.1.0", "docs": "/docs"}
