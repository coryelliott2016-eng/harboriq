"""Staff-side messaging endpoints (Phase 9) — the office side of the
customer portal's messaging thread.

Company-wide `GET/POST /messages` was chosen over nesting exclusively under
`/jobs/{id}/messages`: a message can be general (no `job_id` at all — see
`app.db.models.Message`), so a job-only surface could never show or send
those. A `GET /jobs/{id}/messages` convenience route is included alongside
for the common case of "what has this customer said about this specific
work order", but the company-wide inbox below is the primary surface the
staff "Messages" panel drives.

Gated `require_operations` at the router level, same as `invoices.py` — this
is front-desk work, technicians are not part of it.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_current_user, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.messages import InboxMessageOut, MessageOut, StaffMessageCreate
from app.services import messages as messages_service
from app.services.auth import AuthenticatedUser

router = APIRouter(
    prefix="/messages", tags=["messages"], dependencies=[Depends(require_operations)]
)


@router.get("", response_model=list[InboxMessageOut])
def list_inbox(
    unread_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Every thread in the tenant, newest first — the staff Messages panel's
    main feed. `unread_only=true` narrows to customer messages nobody on
    staff has opened yet."""
    rows = messages_service.list_all_for_company(db, company_id, unread_only=unread_only)
    return [InboxMessageOut.from_row(r) for r in rows]


@router.post("", response_model=MessageOut)
def reply(
    body: StaffMessageCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Staff sends/replies to a customer's thread."""
    with http_errors():
        return messages_service.send_from_staff(
            db, company_id, body.customer_id, user.id, body.body, job_id=body.job_id
        )


@router.post("/{message_id}/read", response_model=MessageOut)
def mark_read(
    message_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return messages_service.mark_read(db, company_id, message_id)


@router.get("/by-job/{job_id}", response_model=list[MessageOut])
def list_for_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Convenience view: every message tied to one job, oldest first."""
    with http_errors():
        return messages_service.list_for_job(db, company_id, job_id)
