"""HarborIQ v2 application entrypoint."""
from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(
    title="HarborIQ",
    version="0.1.0",
    description="Marine service operating system (corrected scaffold).",
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"name": "HarborIQ", "version": "0.1.0", "docs": "/docs"}
