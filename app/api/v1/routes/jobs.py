"""Job (work order) endpoints, including the scheduling board feed.

Authorization has two tiers. Owner/admin/office run the shop: they create,
edit, dispatch and delete work orders. A technician cannot do any of that, but
on a job assigned to *them* they may move the status and record the labor and
parts they used — which is the whole of their day. `deps.authorize_job_action`
is the single place that rule lives.

Status is never set through PATCH. It moves only through
`POST /jobs/{id}/status`, which delegates to `JobSM` in the service layer, so
an illegal move is a 409 rather than a silently corrupt board.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    authorize_job_action,
    get_current_company_id,
    get_current_user,
    get_db,
    require_operations,
)
from app.api.errors import http_errors
from app.db.models import JobPriority, JobStatus
from app.schemas.dispatch_board import OnMyWayResponse
from app.schemas.jobs import (
    JobAssign,
    JobCreate,
    JobDetail,
    JobLineItemCreate,
    JobLineItemOut,
    JobLineItemUpdate,
    JobOut,
    JobStatusUpdate,
    JobUpdate,
)
from app.services import jobs as service
from app.services import outbox
from app.services.auth import AuthenticatedUser
from app.services.outbox_dispatch import dispatch_outbox_soon

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _customer_label(ctx) -> str:
    return ctx.company_name or " ".join(
        filter(None, [ctx.first_name, ctx.last_name])
    ) or "there"


def _enqueue_job_sms(db: Session, company_id: uuid.UUID, ctx, body: str) -> int | None:
    """Best-effort SMS via the outbox — no-op if the customer has no phone
    on file or has opted out (`Customer.sms_opted_out`, Phase 9)."""
    if not ctx.customer_phone or ctx.customer_sms_opted_out:
        return None
    event_id = outbox.enqueue(db, company_id, "sms.send", {"to": ctx.customer_phone, "body": body})
    db.commit()
    return event_id


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_job(
    body: JobCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Open a work order. New jobs start in `scheduled`."""
    with http_errors():
        return service.create(db, company_id, body.model_dump())


@router.get("", response_model=list[JobOut])
def list_jobs(
    job_status: JobStatus | None = Query(default=None, alias="status"),
    priority: JobPriority | None = None,
    technician_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    vessel_id: uuid.UUID | None = None,
    scheduled_from: datetime | None = None,
    scheduled_to: datetime | None = None,
    unassigned: bool = False,
    sort: str = Query(
        default="scheduled_at",
        pattern="^(scheduled_at|priority_score)$",
        description=(
            "`scheduled_at` (default) or `priority_score` — the dispatch-"
            "priority queue, ordered by the cached dispatch score descending."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """The work-order queue. `unassigned=true` is the intake list.

    `?sort=priority_score` returns the same filtered set ordered by the AI
    dispatch engine's cached `dispatch_score` instead of schedule time — the
    "what should get worked next" view (see `app.services.dispatch`).
    """
    with http_errors():
        return service.list_jobs(
            db,
            company_id,
            status=job_status.value if job_status else None,
            priority=priority.value if priority else None,
            technician_id=technician_id,
            customer_id=customer_id,
            vessel_id=vessel_id,
            scheduled_from=scheduled_from,
            scheduled_to=scheduled_to,
            unassigned=unassigned,
            sort=sort,
            limit=limit,
            offset=offset,
        )


# Declared before `/{job_id}` so "schedule" is not parsed as a job id.
@router.get("/schedule", response_model=list[JobOut])
def get_schedule(
    start: datetime | None = None,
    end: datetime | None = None,
    technician_id: uuid.UUID | None = None,
    job_status: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Calendar/board feed: scheduled jobs in `[start, end)`, ordered by time.

    Jobs with no `scheduled_at` are omitted — they belong in the intake queue,
    not on a calendar. `end` is exclusive so adjacent windows tile cleanly.
    """
    if start is not None and end is not None and end < start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "end must not be before start"
        )
    return service.list_schedule(
        db,
        company_id,
        start=start,
        end=end,
        technician_id=technician_id,
        status=job_status.value if job_status else None,
        limit=limit,
    )


@router.get("/{job_id}", response_model=JobDetail)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """A job with its billable lines."""
    with http_errors():
        job = service.get(db, company_id, job_id)
        items = service.list_line_items(db, company_id, job_id)
    detail = JobDetail.model_validate(job)
    detail.line_items = [JobLineItemOut.model_validate(item) for item in items]
    return detail


@router.patch(
    "/{job_id}", response_model=JobOut, dependencies=[Depends(require_operations)]
)
def update_job(
    job_id: uuid.UUID,
    body: JobUpdate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Edit the descriptive and scheduling fields. Status moves elsewhere."""
    with http_errors():
        return service.update(
            db, company_id, job_id, body.model_dump(exclude_unset=True)
        )


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_operations)],
)
def delete_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Delete a job and its line items. 409 if an estimate or invoice cites it."""
    with http_errors():
        service.delete(db, company_id, job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# dispatch + status
# ---------------------------------------------------------------------------
@router.post(
    "/{job_id}/assign",
    response_model=JobOut,
    dependencies=[Depends(require_operations)],
)
def assign_job(
    job_id: uuid.UUID,
    body: JobAssign,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Dispatch the job to a technician, or unassign it with a null id.

    Assigning (not unassigning) best-effort enqueues a job-confirmation SMS
    to the customer, via the same outbox pattern as every other
    notification — a delivery failure here never rolls back the assignment
    itself. This is the SAME endpoint the Phase 7 ranked-candidate list
    (`DispatchSuggestions`) and the Phase 11 drag-and-drop dispatch board
    both call; there is exactly one assignment code path.
    """
    with http_errors():
        row = service.assign(db, company_id, job_id, body.technician_id)
    if body.technician_id is not None:
        with http_errors():
            ctx = service.get_notification_context(db, company_id, job_id)
        when = f" on {ctx.scheduled_at:%b %d at %I:%M %p}" if ctx.scheduled_at else ""
        _enqueue_job_sms(
            db,
            company_id,
            ctx,
            f"Hi {_customer_label(ctx)}, your service \"{ctx.title}\" has been "
            f"scheduled{when}. Reply here with any questions.",
        )
        dispatch_outbox_soon(background_tasks)
    return row


@router.post("/{job_id}/notify-on-my-way", response_model=OnMyWayResponse)
def notify_on_my_way(
    job_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Technician-triggered "on my way" text to the customer.

    Same authorization as moving the job's status
    (`app.api.deps.authorize_job_action`): office staff may trigger this for
    any job, the assigned technician may trigger it for their own job, and
    nobody else may. Best-effort — a missing customer phone number is a
    silent no-op (documented in `_enqueue_job_sms`), not an error, since
    that reflects the shop's own data, not something the caller did wrong.
    """
    authorize_job_action(db, user, job_id)
    with http_errors():
        ctx = service.get_notification_context(db, user.company_id, job_id)
    tech_name = ctx.technician_name or "Your technician"
    event_id = _enqueue_job_sms(
        db,
        user.company_id,
        ctx,
        f"{tech_name} is on the way for your service \"{ctx.title}\".",
    )
    dispatch_outbox_soon(background_tasks)
    return OnMyWayResponse(outbox_event_id=event_id)


@router.post("/{job_id}/status", response_model=JobOut)
def set_job_status(
    job_id: uuid.UUID,
    body: JobStatusUpdate,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Move the job through `JobSM`. Illegal transitions are a 409.

    Office staff may move any job; a technician only the jobs assigned to them.
    """
    authorize_job_action(db, user, job_id)
    with http_errors():
        return service.set_status(
            db, user.company_id, job_id, body.status.value,
            hold_reason=body.hold_reason,
        )


# ---------------------------------------------------------------------------
# line items — labor, parts and fees; the invoicing phase's input
# ---------------------------------------------------------------------------
@router.post(
    "/{job_id}/line-items",
    response_model=JobLineItemOut,
    status_code=status.HTTP_201_CREATED,
)
def add_line_item(
    job_id: uuid.UUID,
    body: JobLineItemCreate,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Record labor, a part or a fee against the job.

    Naming an `inventory_item_id` here only records which part was fitted; it
    does not deduct stock. `POST /api/v1/inventory/use` is the single writer of
    `quantity_on_hand`, and it appends its own line.
    """
    authorize_job_action(db, user, job_id)
    with http_errors():
        return service.add_line_item(db, user.company_id, job_id, body.model_dump())


@router.get("/{job_id}/line-items", response_model=list[JobLineItemOut])
def list_line_items(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        service.get(db, company_id, job_id)
        return service.list_line_items(db, company_id, job_id)


@router.patch("/{job_id}/line-items/{line_item_id}", response_model=JobLineItemOut)
def update_line_item(
    job_id: uuid.UUID,
    line_item_id: uuid.UUID,
    body: JobLineItemUpdate,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Correct a line. 409 once the line has been invoiced."""
    authorize_job_action(db, user, job_id)
    with http_errors():
        return service.update_line_item(
            db,
            user.company_id,
            job_id,
            line_item_id,
            body.model_dump(exclude_unset=True),
        )


@router.delete(
    "/{job_id}/line-items/{line_item_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_line_item(
    job_id: uuid.UUID,
    line_item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Remove a line. 409 once invoiced; stock is not returned automatically."""
    authorize_job_action(db, user, job_id)
    with http_errors():
        service.delete_line_item(db, user.company_id, job_id, line_item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
