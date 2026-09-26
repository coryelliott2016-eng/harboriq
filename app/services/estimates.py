"""Estimates — staff-authored, customer-approved, converted into invoices.

Lifecycle (enforced by `EstimateSM`):

    draft --send--> sent --(customer approves in portal)--> approved --convert--> invoiced
                        \\--> declined / expired

* Creation, sending and conversion are staff actions (owner/admin/office).
* Approval stays where it already lives: the customer portal hands a scoped
  `estimate_approve` token to `POST /public/estimate/{token}/approve`, which
  records IP, user agent and document version in `audit_log`.
* Conversion copies the estimate's lines onto the job as `job_line_items`
  and freezes exactly those rows onto a new draft invoice (with
  `invoices.estimate_id` set). Other uninvoiced lines already on the job are
  left alone, so an estimate never silently bills unrelated work.

Every write runs inside `tenant_context` on the app role — RLS, not a
remembered WHERE clause, keeps tenants apart — and every status transition
loads the row `FOR UPDATE` before `EstimateSM.assert_transition`, matching
`invoices.py`.
"""
from __future__ import annotations

import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.tenant import tenant_context
from app.services import outbox
from app.services.crud import Conflict, NotFound, ValidationFailed
from app.services.state_machines import EstimateSM

_TERMINAL_JOB_STATUSES = {"canceled"}


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _audit(
    db: Session,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    estimate_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append an audit row inside the caller's transaction (caller commits)."""
    db.execute(
        text(
            """
            INSERT INTO audit_log
                (company_id, actor_user_id, action, resource_type, resource_id, metadata)
            VALUES (:cid, :actor, :action, 'estimate', :rid, CAST(:meta AS jsonb))
            """
        ),
        {
            "cid": company_id,
            "actor": actor_user_id,
            "action": action,
            "rid": estimate_id,
            "meta": json.dumps(metadata or {}),
        },
    )


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
def create_estimate(
    db: Session,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    line_items: list[dict[str, Any]],
    *,
    tax_rate: Decimal = Decimal("0"),
    notes: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Create a `draft` estimate for `job_id` with its priced lines."""
    if not line_items:
        raise ValidationFailed("an estimate needs at least one line item")
    for line in line_items:
        if line.get("inventory_item_id") is not None and line["kind"] != "part":
            raise ValidationFailed("only a 'part' line may reference an inventory item")

    try:
        with tenant_context(db, company_id):
            job = db.execute(
                text("SELECT id, customer_id, status FROM jobs WHERE id = :id"),
                {"id": job_id},
            ).first()
            if job is None:
                db.rollback()
                raise NotFound(f"job {job_id} not found")
            if str(job.status) in _TERMINAL_JOB_STATUSES:
                db.rollback()
                raise Conflict("cannot estimate a canceled job")

            for line in line_items:
                if line.get("inventory_item_id") is not None:
                    found = db.execute(
                        text("SELECT 1 FROM inventory_items WHERE id = :id"),
                        {"id": line["inventory_item_id"]},
                    ).first()
                    if found is None:
                        db.rollback()
                        raise NotFound("inventory item not found")

            subtotal = sum(
                (_quantize(Decimal(li["quantity"]) * Decimal(li["unit_price"]))
                 for li in line_items),
                Decimal("0"),
            )
            taxable = sum(
                (_quantize(Decimal(li["quantity"]) * Decimal(li["unit_price"]))
                 for li in line_items if li.get("taxable", True)),
                Decimal("0"),
            )
            tax_total = _quantize(taxable * tax_rate)
            total = subtotal + tax_total

            estimate = db.execute(
                text(
                    """
                    INSERT INTO estimates
                        (company_id, job_id, customer_id, status, subtotal,
                         tax_rate, tax_total, total, balance_due, notes)
                    VALUES
                        (:cid, :job_id, :customer_id, 'draft', :subtotal,
                         :tax_rate, :tax_total, :total, :total, :notes)
                    RETURNING *
                    """
                ),
                {
                    "cid": company_id,
                    "job_id": job_id,
                    "customer_id": job.customer_id,
                    "subtotal": subtotal,
                    "tax_rate": tax_rate,
                    "tax_total": tax_total,
                    "total": total,
                    "notes": notes,
                },
            ).first()

            for position, line in enumerate(line_items):
                db.execute(
                    text(
                        """
                        INSERT INTO estimate_line_items
                            (estimate_id, inventory_item_id, description, quantity,
                             unit_price, kind, taxable, position)
                        VALUES
                            (:eid, :inv, :description, :quantity, :unit_price,
                             CAST(:kind AS job_line_item_kind), :taxable, :position)
                        """
                    ),
                    {
                        "eid": estimate.id,
                        "inv": line.get("inventory_item_id"),
                        "description": line["description"],
                        "quantity": line["quantity"],
                        "unit_price": line.get("unit_price", 0),
                        "kind": line["kind"],
                        "taxable": line.get("taxable", True),
                        "position": position,
                    },
                )

            _audit(
                db, company_id, actor_user_id, "estimate.created", estimate.id,
                {"job_id": str(job_id), "total": str(total), "lines": len(line_items)},
            )
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("estimate violates a database constraint") from exc

    return get_detail(db, company_id, estimate.id)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
def get(db: Session, company_id: uuid.UUID, estimate_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM estimates WHERE id = :id"), {"id": estimate_id}
        ).first()
    if row is None:
        raise NotFound(f"estimate {estimate_id} not found")
    return row


def list_line_items(db: Session, company_id: uuid.UUID, estimate_id: uuid.UUID) -> list[Row]:
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM estimate_line_items
                     WHERE estimate_id = :id
                     ORDER BY position, created_at, id
                    """
                ),
                {"id": estimate_id},
            ).all()
        )


def _invoice_id_for(db: Session, company_id: uuid.UUID, estimate_id: uuid.UUID) -> uuid.UUID | None:
    with tenant_context(db, company_id):
        row = db.execute(
            text(
                """
                SELECT id FROM invoices
                 WHERE estimate_id = :id AND status <> 'void'
                 ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"id": estimate_id},
        ).first()
    return row.id if row else None


def get_detail(db: Session, company_id: uuid.UUID, estimate_id: uuid.UUID) -> dict[str, Any]:
    estimate = get(db, company_id, estimate_id)
    return {
        "estimate": estimate,
        "line_items": list_line_items(db, company_id, estimate_id),
        "invoice_id": _invoice_id_for(db, company_id, estimate_id),
    }


def list_estimates(
    db: Session,
    company_id: uuid.UUID,
    *,
    status: str | None = None,
    job_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Row]:
    clauses = ""
    params: dict[str, Any] = {"cid": company_id, "limit": limit, "offset": offset}
    if status is not None:
        clauses += " AND status = CAST(:status AS estimate_status)"
        params["status"] = status
    if job_id is not None:
        clauses += " AND job_id = :job_id"
        params["job_id"] = job_id
    if customer_id is not None:
        clauses += " AND customer_id = :customer_id"
        params["customer_id"] = customer_id
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM estimates
                     WHERE company_id = :cid {clauses}
                     ORDER BY created_at DESC
                     LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            ).all()
        )


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def send_estimate(
    db: Session,
    company_id: uuid.UUID,
    estimate_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """`draft -> sent`, then queue the customer's portal link by email.

    The customer reviews and approves inside the existing portal, which
    issues its own short-lived `estimate_approve` token — so no approval
    capability is ever placed in an email body. If the customer has no email
    on file the estimate is still marked sent and `email_queued` is False.
    """
    from app.services.portal import issue_portal_token

    with tenant_context(db, company_id):
        current = db.execute(
            text("SELECT status, customer_id FROM estimates WHERE id = :id FOR UPDATE"),
            {"id": estimate_id},
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"estimate {estimate_id} not found")
        try:
            EstimateSM.assert_transition(str(current.status), "sent")
        except Exception:
            db.rollback()
            raise

        customer_email = None
        if current.customer_id is not None:
            cust = db.execute(
                text("SELECT email FROM customers WHERE id = :id"),
                {"id": current.customer_id},
            ).first()
            customer_email = cust.email if cust else None

        estimate = db.execute(
            text(
                """
                UPDATE estimates
                   SET status = 'sent', sent_at = now(), updated_at = now()
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"id": estimate_id},
        ).first()
        _audit(db, company_id, actor_user_id, "estimate.sent", estimate_id,
               {"email_queued": bool(customer_email)})
        db.commit()

    email_queued = False
    if customer_email and current.customer_id is not None:
        # `issue_portal_token` commits on its own; the status change above is
        # already durable, so a failure here leaves a sent estimate the shop
        # can re-share via "Send portal invite" rather than a half-state.
        raw = issue_portal_token(db, company_id, current.customer_id)
        base_url = settings.app_base_url.rstrip("/")
        with tenant_context(db, company_id):
            outbox.enqueue(
                db,
                company_id,
                "estimate.send",
                {
                    "estimate_id": str(estimate_id),
                    "customer_email": customer_email,
                    "portal_url": f"{base_url}/portal/{raw}/estimates",
                    "total": str(estimate.total),
                },
            )
            db.commit()
        email_queued = True

    return {"estimate": estimate, "email_queued": email_queued}


def convert_to_invoice(
    db: Session,
    company_id: uuid.UUID,
    estimate_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """`approved -> invoiced`: bill exactly the approved lines.

    Copies each estimate line onto the job as a `job_line_items` row and
    freezes those rows onto a new `draft` invoice in the same transaction.
    The invoice then follows the existing send/pay/refund lifecycle.
    """
    with tenant_context(db, company_id):
        est = db.execute(
            text(
                """
                SELECT id, status, job_id, customer_id, tax_rate
                  FROM estimates WHERE id = :id FOR UPDATE
                """
            ),
            {"id": estimate_id},
        ).first()
        if est is None:
            db.rollback()
            raise NotFound(f"estimate {estimate_id} not found")
        try:
            EstimateSM.assert_transition(str(est.status), "invoiced")
        except Exception:
            db.rollback()
            raise
        if est.job_id is None:
            db.rollback()
            raise Conflict("estimate is not attached to a job; create the invoice manually")

        lines = db.execute(
            text(
                """
                SELECT kind, description, quantity, unit_price, taxable, inventory_item_id
                  FROM estimate_line_items
                 WHERE estimate_id = :id
                 ORDER BY position, created_at, id
                """
            ),
            {"id": estimate_id},
        ).all()
        if not lines:
            db.rollback()
            raise Conflict("estimate has no line items to invoice")

        subtotal = sum((_quantize(r.quantity * r.unit_price) for r in lines), Decimal("0"))
        taxable_subtotal = sum(
            (_quantize(r.quantity * r.unit_price) for r in lines if r.taxable), Decimal("0")
        )
        tax_total = _quantize(taxable_subtotal * est.tax_rate)
        total = subtotal + tax_total

        invoice = db.execute(
            text(
                """
                INSERT INTO invoices
                    (company_id, estimate_id, customer_id, status, subtotal,
                     tax_total, total, amount_paid, balance_due, tax_rate)
                VALUES
                    (:cid, :eid, :customer_id, 'draft', :subtotal,
                     :tax_total, :total, 0, :total, :tax_rate)
                RETURNING id
                """
            ),
            {
                "cid": company_id,
                "eid": estimate_id,
                "customer_id": est.customer_id,
                "subtotal": subtotal,
                "tax_total": tax_total,
                "total": total,
                "tax_rate": est.tax_rate,
            },
        ).first()

        for r in lines:
            db.execute(
                text(
                    """
                    INSERT INTO job_line_items
                        (company_id, job_id, kind, description, inventory_item_id,
                         quantity, unit_price, taxable, invoice_id, invoiced_at)
                    VALUES
                        (:cid, :job_id, CAST(:kind AS job_line_item_kind), :description,
                         :inv, :quantity, :unit_price, :taxable, :invoice_id, now())
                    """
                ),
                {
                    "cid": company_id,
                    "job_id": est.job_id,
                    "kind": str(r.kind),
                    "description": r.description or "Estimate line",
                    "inv": r.inventory_item_id,
                    "quantity": r.quantity,
                    "unit_price": r.unit_price,
                    "taxable": r.taxable,
                    "invoice_id": invoice.id,
                },
            )

        estimate = db.execute(
            text(
                """
                UPDATE estimates SET status = 'invoiced', updated_at = now()
                 WHERE id = :id RETURNING *
                """
            ),
            {"id": estimate_id},
        ).first()
        _audit(db, company_id, actor_user_id, "estimate.invoiced", estimate_id,
               {"invoice_id": str(invoice.id), "total": str(total)})
        db.commit()

    return {"estimate": estimate, "invoice_id": invoice.id}
