"""Tenant audit-trail viewer (v0.2.1).

Owner/admin only. Read-only by construction: `audit_log` rejects UPDATE and
DELETE at the database level, and RLS limits every query to the caller's
tenant, so this endpoint can never be used to alter or cross-read history.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_admin
from app.db.tenant import tenant_context
from app.schemas.audit import AuditLogEntryOut, AuditLogPage
from app.services import audit as audit_service
from app.services.auth import AuthenticatedUser

router = APIRouter(
    prefix="/audit-log", tags=["audit"], dependencies=[Depends(require_admin)]
)


@router.get("", response_model=AuditLogPage)
def list_audit_log(
    action: str | None = Query(
        default=None,
        max_length=100,
        description="Exact action, or a prefix ending in '.' such as 'invoice.'",
    ),
    resource_type: str | None = Query(default=None, max_length=50),
    resource_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=audit_service.DEFAULT_PAGE_SIZE, ge=1,
                       le=audit_service.MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Newest-first, keyset-paginated audit entries for the caller's company."""
    with tenant_context(db, user.company_id):
        rows = audit_service.list_entries(
            db,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            before_id=before_id,
            limit=limit,
        )
    items = [AuditLogEntryOut.model_validate(row) for row in rows]
    next_before_id = items[-1].id if len(items) == limit else None
    return AuditLogPage(items=items, next_before_id=next_before_id)
