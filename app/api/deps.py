"""Shared FastAPI dependencies."""
from __future__ import annotations

import uuid

from fastapi import Request

from app.db.session import get_db, get_service_db
from app.db.tenant import require_tenant_company_id


def current_company_id(request: Request) -> uuid.UUID:
    """Extract the acting tenant's company id.

    Scaffold/dev: X-Company-Id header. Replace with real session/JWT auth.
    """
    return require_tenant_company_id(request)


__all__ = ["get_db", "get_service_db", "current_company_id"]
