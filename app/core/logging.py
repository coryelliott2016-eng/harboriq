"""Structured logging via structlog."""
from __future__ import annotations

import logging

import structlog

from app.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(level=settings.log_level)
    # Human-readable console output is fine (and nicer) for a developer's
    # terminal, but a real deployment ships logs to something that parses
    # them (journald, Docker's log driver, eventually Loki/CloudWatch/etc.)
    # — those consumers want one JSON object per line, not ANSI-colored
    # key=value pairs. Branch on `app_env` the same way `config.py` already
    # branches JWT-secret strictness on development vs. not, rather than
    # inventing a second toggle.
    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.app_env == "development"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
    )


log = structlog.get_logger()
