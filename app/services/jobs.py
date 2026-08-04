"""Jobs (work orders) — tenant-scoped CRUD, scheduling, and status transitions.

Status is never written directly. `set_status` reloads the row `FOR UPDATE`,
hands the current and target values to the existing
`app.services.state_machines.JobSM`, and only then writes — the same pattern the
module docstring of `state_machines.py` prescribes. Taking the row lock before
asserting is what makes it safe under concurrency: two racing requests to move
`scheduled -> in_progress` serialise, and the loser re-reads `in_progress` and
is rejected by the state machine rather than silently double-applying.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import JOB_ASSIGNABLE_ROLES, JobLineItemKind, JobStatus
from app.db.tenant import tenant_context
from app.services.crud import Conflict, NotFound, ValidationFailed, assignments
from app.services.state_machines import JobSM

UPDATABLE_COLUMNS = frozenset(
    {
        "customer_id", "vessel_id", "title", "description", "priority",
        "scheduled_at", "scheduled_end_at", "technician_id", "notes",
        "required_skills",
    }
)

_INSERT_COLUMNS = sorted(UPDATABLE_COLUMNS)

_INSERT = text(
    f"""
    INSERT INTO jobs (company_id, {", ".join(_INSERT_COLUMNS)})
    VALUES (:company_id, {", ".join(f":{c}" for c in _INSERT_COLUMNS)})
    RETURNING *
    """
)

LINE_ITEM_UPDATABLE_COLUMNS = frozenset(
    {"description", "quantity", "unit_price", "taxable"}
)


class InvalidTechnician(Exception):
    """The proposed assignee is not a user in this tenant who can hold a job."""


def _map_integrity_error(exc: IntegrityError) -> Exception:
    detail = str(exc.orig)
    if "fk_jobs_customer" in detail:
        return NotFound("customer not found")
    if "fk_jobs_vessel" in detail:
        return NotFound("vessel not found")
    if "fk_jobs_technician" in detail:
        return InvalidTechnician("technician not found")
    if "ck_jobs_schedule_window" in detail:
        return ValidationFailed("scheduled_end_at must not be before scheduled_at")
    if "ck_jobs_title_not_blank" in detail:
        return ValidationFailed("title must not be blank")
    if "fk_job_line_items_job" in detail:
        return NotFound("job not found")
    if "ck_job_line_items_stock_is_a_part" in detail:
        return ValidationFailed("only a 'part' line may reference an inventory item")
    return Conflict("job violates a database constraint")


# ---------------------------------------------------------------------------
# reference checks (assume RLS is already armed by the caller)
# ---------------------------------------------------------------------------
def _require_row(db: Session, table: str, row_id: uuid.UUID, label: str) -> None:
    # `table` is a literal from this module, never caller input.
    found = db.execute(
        text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": row_id}
    ).first()
    if found is None:
        raise NotFound(f"{label} {row_id} not found")


def _require_assignable_technician(db: Session, technician_id: uuid.UUID) -> None:
    """The assignee must be an active user of this tenant who performs work.

    Front-desk (`office`) users are excluded: a work order is dispatched to
    somebody who turns wrenches. Owners and admins are allowed because in a
    small yard they do the work themselves.
    """
    row = db.execute(
        text("SELECT role, is_active FROM users WHERE id = :id"),
        {"id": technician_id},
    ).first()
    if row is None:
        raise InvalidTechnician(f"user {technician_id} not found")
    if not row.is_active:
        raise InvalidTechnician(f"user {technician_id} is not active")
    if row.role not in {role.value for role in JOB_ASSIGNABLE_ROLES}:
        raise InvalidTechnician(
            f"role {row.role!r} cannot be assigned a job; "
            f"allowed: {sorted(r.value for r in JOB_ASSIGNABLE_ROLES)}"
        )


def _validate_references(db: Session, data: dict[str, Any]) -> None:
    if data.get("customer_id") is not None:
        _require_row(db, "customers", data["customer_id"], "customer")
    if data.get("vessel_id") is not None:
        _require_row(db, "vessels", data["vessel_id"], "vessel")
    if data.get("technician_id") is not None:
        _require_assignable_technician(db, data["technician_id"])


def _require_vessel_belongs_to_customer(
    db: Session, customer_id: uuid.UUID, vessel_id: uuid.UUID
) -> None:
    """A job's vessel must be one of that job's customer's boats.

    The composite FKs guarantee both rows are in the tenant but say nothing
    about them agreeing with each other, so scheduling work on someone else's
    boat under your own name is checked here.
    """
    row = db.execute(
        text("SELECT 1 FROM vessels WHERE id = :vid AND customer_id = :cust"),
        {"vid": vessel_id, "cust": customer_id},
    ).first()
    if row is None:
        raise ValidationFailed("vessel does not belong to this customer")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create(db: Session, company_id: uuid.UUID, data: dict[str, Any]) -> Row:
    params = {"company_id": company_id} | {
        column: data.get(column) for column in _INSERT_COLUMNS
    }
    if params.get("priority") is None:
        params["priority"] = "normal"

    try:
        with tenant_context(db, company_id):
            _validate_references(db, params)
            if params["vessel_id"] is not None:
                _require_vessel_belongs_to_customer(
                    db, params["customer_id"], params["vessel_id"]
                )
            row = db.execute(_INSERT, params).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


def get(db: Session, company_id: uuid.UUID, job_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id}
        ).first()
    if row is None:
        raise NotFound(f"job {job_id} not found")
    return row


#: `sort=priority_score` (see B3 of the dispatch-engine spec) orders the
#: queue by the cached `dispatch_score` instead of by schedule time — "what
#: should get worked next" rather than "what's on the calendar". Jobs never
#: scored yet (`dispatch_score IS NULL`) sort last, since an unscored job is
#: not known to be low priority, just not yet evaluated.
_ORDER_BY_CLAUSES: dict[str, str] = {
    "scheduled_at": "ORDER BY scheduled_at NULLS LAST, created_at",
    "priority_score": "ORDER BY dispatch_score DESC NULLS LAST, created_at",
}


def list_jobs(
    db: Session,
    company_id: uuid.UUID,
    *,
    status: str | None = None,
    priority: str | None = None,
    technician_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    vessel_id: uuid.UUID | None = None,
    scheduled_from: datetime | None = None,
    scheduled_to: datetime | None = None,
    unassigned: bool = False,
    sort: str = "scheduled_at",
    limit: int = 50,
    offset: int = 0,
) -> list[Row]:
    """Filtered job list. Every fragment below is a literal; values are bound.

    `sort` is one of `scheduled_at` (default, the existing behaviour) or
    `priority_score` (the dispatch-priority queue — "what should get worked
    next", ordered by the cached `dispatch_score` descending).
    """
    if sort not in _ORDER_BY_CLAUSES:
        raise ValidationFailed(f"sort must be one of {sorted(_ORDER_BY_CLAUSES)}")

    clauses = ""
    params: dict[str, Any] = {"cid": company_id, "limit": limit, "offset": offset}

    for column, value in (
        ("status", status),
        ("priority", priority),
        ("technician_id", technician_id),
        ("customer_id", customer_id),
        ("vessel_id", vessel_id),
    ):
        if value is not None:
            clauses += f" AND {column} = :{column}"
            params[column] = value

    if unassigned:
        clauses += " AND technician_id IS NULL"
    if scheduled_from is not None:
        clauses += " AND scheduled_at >= :scheduled_from"
        params["scheduled_from"] = scheduled_from
    if scheduled_to is not None:
        clauses += " AND scheduled_at < :scheduled_to"
        params["scheduled_to"] = scheduled_to

    order_by = _ORDER_BY_CLAUSES[sort]
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM jobs
                     WHERE company_id = :cid {clauses}
                     {order_by}
                     LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            ).all()
        )


def list_schedule(
    db: Session,
    company_id: uuid.UUID,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    technician_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 500,
) -> list[Row]:
    """Calendar/board feed: scheduled jobs in a window, optionally per technician.

    Unscheduled jobs are excluded — a calendar cannot place a job with no time.
    Use `GET /jobs?unassigned=true` or a plain list for the intake queue. The
    `end` bound is exclusive so consecutive day/week windows neither overlap nor
    drop a job landing exactly on the boundary.
    """
    clauses = " AND scheduled_at IS NOT NULL"
    params: dict[str, Any] = {"cid": company_id, "limit": limit}

    if start is not None:
        clauses += " AND scheduled_at >= :start"
        params["start"] = start
    if end is not None:
        clauses += " AND scheduled_at < :end"
        params["end"] = end
    if technician_id is not None:
        clauses += " AND technician_id = :technician_id"
        params["technician_id"] = technician_id
    if status is not None:
        clauses += " AND status = :status"
        params["status"] = status

    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM jobs
                     WHERE company_id = :cid {clauses}
                     ORDER BY scheduled_at, created_at
                     LIMIT :limit
                    """
                ),
                params,
            ).all()
        )


def update(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID, changes: dict[str, Any]
) -> Row:
    if not changes:
        return get(db, company_id, job_id)
    for column, message in (
        ("customer_id", "a job must belong to a customer"),
        ("title", "title is required"),
    ):
        if column in changes and changes[column] is None:
            raise ValidationFailed(message)

    statement = text(
        f"""
        UPDATE jobs
           SET {assignments(changes, UPDATABLE_COLUMNS)}, updated_at = now()
         WHERE id = :id
        RETURNING *
        """
    )
    try:
        with tenant_context(db, company_id):
            _validate_references(db, changes)
            current = db.execute(
                text("SELECT customer_id, vessel_id FROM jobs WHERE id = :id"),
                {"id": job_id},
            ).first()
            if current is None:
                raise NotFound(f"job {job_id} not found")

            # Re-check the pairing against the post-patch values, since either
            # side may be the thing being changed.
            customer_id = changes.get("customer_id", current.customer_id)
            vessel_id = changes.get("vessel_id", current.vessel_id)
            if vessel_id is not None and (
                "customer_id" in changes or "vessel_id" in changes
            ):
                _require_vessel_belongs_to_customer(db, customer_id, vessel_id)

            row = db.execute(statement, changes | {"id": job_id}).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


def delete(db: Session, company_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Delete a job and its line items (the FK cascades)."""
    with tenant_context(db, company_id):
        try:
            row = db.execute(
                text("DELETE FROM jobs WHERE id = :id RETURNING id"), {"id": job_id}
            ).first()
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise Conflict(
                "job is referenced by an estimate or invoice and cannot be deleted"
            ) from exc
    if row is None:
        raise NotFound(f"job {job_id} not found")


# ---------------------------------------------------------------------------
# assignment + status
# ---------------------------------------------------------------------------
def assign(
    db: Session,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    technician_id: uuid.UUID | None,
) -> Row:
    """Assign (or, with None, unassign) the job's technician."""
    try:
        with tenant_context(db, company_id):
            if technician_id is not None:
                _require_assignable_technician(db, technician_id)
            row = db.execute(
                text(
                    """
                    UPDATE jobs
                       SET technician_id = :tech, updated_at = now()
                     WHERE id = :id
                    RETURNING *
                    """
                ),
                {"tech": technician_id, "id": job_id},
            ).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    if row is None:
        raise NotFound(f"job {job_id} not found")
    return row


#: Extra columns written alongside each target status. Fragments are literals.
_STATUS_SIDE_EFFECTS: dict[str, str] = {
    # COALESCE so resuming from on_hold keeps the original start time.
    JobStatus.IN_PROGRESS.value: ", started_at = COALESCE(started_at, now()),"
                                 " hold_reason = NULL",
    JobStatus.ON_HOLD.value: ", hold_reason = :hold_reason",
    JobStatus.COMPLETED.value: ", completed_at = now()",
    JobStatus.CANCELED.value: ", canceled_at = now()",
}


def set_status(
    db: Session,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    target: str,
    *,
    hold_reason: str | None = None,
) -> Row:
    """Move a job to `target`, validating the transition against `JobSM`.

    Raises `NotFound` if the job is not in this tenant and
    `state_machines.IllegalTransition` if the move is not permitted from the
    job's actual, freshly locked current status.
    """
    target = JobStatus(target).value
    extra = _STATUS_SIDE_EFFECTS.get(target, "")
    params: dict[str, Any] = {"id": job_id, "status": target}
    if target == JobStatus.ON_HOLD.value:
        params["hold_reason"] = hold_reason

    with tenant_context(db, company_id):
        current = db.execute(
            text("SELECT status FROM jobs WHERE id = :id FOR UPDATE"), {"id": job_id}
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"job {job_id} not found")

        # Raises IllegalTransition; the row lock is released by the rollback.
        try:
            JobSM.assert_transition(current.status, target)
        except Exception:
            db.rollback()
            raise

        row = db.execute(
            text(
                f"""
                UPDATE jobs
                   SET status = CAST(:status AS job_status){extra}, updated_at = now()
                 WHERE id = :id
                RETURNING *
                """
            ),
            params,
        ).first()
        db.commit()
    return row


# ---------------------------------------------------------------------------
# line items — the invoicing phase's input
# ---------------------------------------------------------------------------
def add_line_item(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID, data: dict[str, Any]
) -> Row:
    """Append a labor/part/fee line.

    Recording a part here does NOT move inventory: stock is deducted only by
    `POST /api/v1/inventory/use`, which appends its own committed line. This
    keeps one writer for `quantity_on_hand`.
    """
    if (
        data.get("inventory_item_id") is not None
        and data["kind"] != JobLineItemKind.PART.value
    ):
        raise ValidationFailed("only a 'part' line may reference an inventory item")

    try:
        with tenant_context(db, company_id):
            _require_row(db, "jobs", job_id, "job")
            if data.get("inventory_item_id") is not None:
                _require_row(
                    db, "inventory_items", data["inventory_item_id"], "inventory item"
                )
            row = db.execute(
                text(
                    """
                    INSERT INTO job_line_items
                        (company_id, job_id, kind, description, inventory_item_id,
                         quantity, unit_price, taxable)
                    VALUES
                        (:company_id, :job_id, CAST(:kind AS job_line_item_kind),
                         :description, :inventory_item_id, :quantity, :unit_price,
                         :taxable)
                    RETURNING *
                    """
                ),
                {
                    "company_id": company_id,
                    "job_id": job_id,
                    "kind": data["kind"],
                    "description": data["description"],
                    "inventory_item_id": data.get("inventory_item_id"),
                    "quantity": data["quantity"],
                    "unit_price": data.get("unit_price", 0),
                    "taxable": data.get("taxable", True),
                },
            ).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


def list_line_items(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID
) -> list[Row]:
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM job_line_items
                     WHERE job_id = :job_id
                     ORDER BY created_at, id
                    """
                ),
                {"job_id": job_id},
            ).all()
        )


def update_line_item(
    db: Session,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    line_item_id: uuid.UUID,
    changes: dict[str, Any],
) -> Row:
    """Edit a line item. Refused once the line has been invoiced."""
    if not changes:
        return _get_line_item(db, company_id, job_id, line_item_id)

    statement = text(
        f"""
        UPDATE job_line_items
           SET {assignments(changes, LINE_ITEM_UPDATABLE_COLUMNS)}, updated_at = now()
         WHERE id = :id AND job_id = :job_id AND invoice_id IS NULL
        RETURNING *
        """
    )
    try:
        with tenant_context(db, company_id):
            row = db.execute(
                statement, changes | {"id": line_item_id, "job_id": job_id}
            ).first()
            if row is None:
                db.rollback()
                _raise_line_item_conflict(db, company_id, job_id, line_item_id)
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


def delete_line_item(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID, line_item_id: uuid.UUID
) -> None:
    """Remove a line item. Refused once invoiced.

    A committed part line is removable — the shop may have mis-scanned it — but
    the stock movement is NOT reversed here, because inventory has exactly one
    writer. Put the part back with a separate inventory adjustment.
    """
    with tenant_context(db, company_id):
        row = db.execute(
            text(
                """
                DELETE FROM job_line_items
                 WHERE id = :id AND job_id = :job_id AND invoice_id IS NULL
                RETURNING id
                """
            ),
            {"id": line_item_id, "job_id": job_id},
        ).first()
        if row is None:
            db.rollback()
            _raise_line_item_conflict(db, company_id, job_id, line_item_id)
        db.commit()


def _get_line_item(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID, line_item_id: uuid.UUID
) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM job_line_items WHERE id = :id AND job_id = :job_id"),
            {"id": line_item_id, "job_id": job_id},
        ).first()
    if row is None:
        raise NotFound(f"line item {line_item_id} not found")
    return row


def _raise_line_item_conflict(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID, line_item_id: uuid.UUID
) -> None:
    """Distinguish "no such line" (404) from "already invoiced" (409)."""
    with tenant_context(db, company_id):
        row = db.execute(
            text(
                """
                SELECT invoice_id FROM job_line_items
                 WHERE id = :id AND job_id = :job_id
                """
            ),
            {"id": line_item_id, "job_id": job_id},
        ).first()
    if row is None:
        raise NotFound(f"line item {line_item_id} not found")
    raise Conflict("line item has been invoiced and can no longer be changed")
