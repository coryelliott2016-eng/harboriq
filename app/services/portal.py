"""Customer self-service portal (Phase 9) — magic-link session + scoped reads.

Portal access model — Option A from the phase spec (see also
`alembic/sql/0008_customer_portal.sql` and README "Customer portal"): a
durable, revocable `public_tokens` row (`resource_type="customer"`,
`purpose="portal"`) rather than a real customer login. This is a pure
extension of the exact machinery `app.services.public_tokens` already
provides for estimate-approve/invoice-pay links — no parallel auth system.

Two isolation guarantees matter here, and they are NOT the same guarantee:
  1. Tenant isolation — a portal token from Company A must never resolve
     data belonging to Company B. This is what `resolve_portal_token`
     (built on `public_tokens.resolve_read_only_token`) plus `tenant_context`
     already give every other public-token flow: the token is looked up
     GLOBALLY via the service role, and everything after that point runs
     inside `tenant_context(db, company_id)` so RLS enforces the company
     boundary the same way it does for an authenticated staff request.
  2. Customer isolation WITHIN a tenant — a portal token issued to Customer A
     must never resolve Customer B's jobs/invoices/vessels/messages even
     though they share a `company_id` and RLS alone cannot tell them apart
     (RLS's unit of isolation is the tenant, not the individual customer).
     Every read below is therefore ALSO filtered by `customer_id = :cid` in
     the SQL itself, not just company_id — this module is the enforcement
     point for that narrower scope, and `tests/test_portal_access.py` /
     `tests/test_portal_data.py` assert it directly (issue a token for
     Customer A, prove Customer B's rows never come back).

`resolve_portal_token` deliberately never consumes a token use (same
reasoning as `invoice_pay`): a customer may open their one durable link many
times over its 90-day life, and nothing here is a one-shot action the way
estimate approval is.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.tenant import tenant_context
from app.services import outbox
from app.services.crud import NotFound
from app.services.public_tokens import issue_public_token, resolve_read_only_token

#: A durable magic link, not a one-off action link — 90 days, renewable by
#: staff re-issuing (`POST /customers/{id}/portal-invite`), per the spec's
#: Option A guidance. Renewal is "issue a fresh row"; the old row is left to
#: expire naturally (or can be revoked) rather than mutated in place, exactly
#: how every other `public_tokens` purpose already treats re-sends.
PORTAL_TOKEN_TTL_HOURS = 24 * 90

#: "Effectively unlimited within that window" per the spec — a customer
#: opening their portal, refreshing, checking invoices weekly, etc. for 90
#: days comfortably fits under a four-digit ceiling, and a hard ceiling
#: (rather than true infinity) still bounds abuse of a leaked link before it
#: naturally expires or is revoked.
PORTAL_TOKEN_MAX_USES = 10_000


def issue_portal_token(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> str:
    """Issue (or re-issue) a customer's durable portal magic link."""
    return issue_public_token(
        db,
        company_id,
        resource_type="customer",
        resource_id=customer_id,
        purpose="portal",
        ttl_hours=PORTAL_TOKEN_TTL_HOURS,
        max_uses=PORTAL_TOKEN_MAX_USES,
    )


def resolve_portal_token(db: Session, raw_token: str) -> dict[str, uuid.UUID]:
    """Resolve a portal token to `{"company_id", "customer_id"}` without
    consuming a use. Raises `InvalidToken` for anything not a live, unrevoked,
    unexpired `portal`/`customer` token — the same 404-not-401 contract as
    every other public-token endpoint (never confirm a token's existence)."""
    resolved = resolve_read_only_token(db, raw_token, purpose="portal", resource_type="customer")
    return {"company_id": resolved["company_id"], "customer_id": resolved["resource_id"]}


# ---------------------------------------------------------------------------
# scoped reads — every query filters by customer_id, not just company_id
# ---------------------------------------------------------------------------
def get_profile(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> dict[str, Any]:
    """The customer's own profile + their vessels."""
    with tenant_context(db, company_id):
        customer = db.execute(
            text("SELECT * FROM customers WHERE id = :id"), {"id": customer_id}
        ).first()
        if customer is None:
            raise NotFound(f"customer {customer_id} not found")
        vessels = db.execute(
            text(
                "SELECT * FROM vessels WHERE customer_id = :cid ORDER BY created_at"
            ),
            {"cid": customer_id},
        ).all()
    return {"customer": customer, "vessels": list(vessels)}


def list_jobs(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> list[Row]:
    """The customer's job/service history: status, schedule, technician name
    only — no internal notes/pricing, which stay staff-only."""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT j.id, j.title, j.status, j.scheduled_at, j.scheduled_end_at,
                           j.completed_at, j.vessel_id,
                           u.full_name AS technician_name
                      FROM jobs j
                      LEFT JOIN users u ON u.id = j.technician_id
                     WHERE j.customer_id = :cid
                     ORDER BY j.scheduled_at DESC NULLS LAST, j.created_at DESC
                    """
                ),
                {"cid": customer_id},
            ).all()
        )


def list_invoices(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> list[Row]:
    """The customer's invoices — paid, outstanding, refunded/partially
    refunded — with balance due. Payment itself reuses the existing
    `invoice_pay` public-token checkout flow; this is a read-only list."""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM invoices
                     WHERE customer_id = :cid
                     ORDER BY created_at DESC
                    """
                ),
                {"cid": customer_id},
            ).all()
        )


def list_estimates(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> list[Row]:
    """The customer's pending/past estimates. Approval itself reuses the
    existing `approve_estimate_with_token`/`estimate_approve` logic — this is
    a read-only list, and the portal only ever surfaces a customer's OWN
    `estimate_approve` token for an estimate that is actually theirs."""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM estimates
                     WHERE customer_id = :cid
                     ORDER BY created_at DESC
                    """
                ),
                {"cid": customer_id},
            ).all()
        )


def list_dock_locations(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> list[Row]:
    """GPS "find my dock" (Phase 17, Area D): this customer's own active/
    upcoming slip reservation(s) with the slip's coordinates, for a
    customer-facing map. `checked_in`/`confirmed` reservations only --
    `pending` (not yet confirmed by staff), `checked_out`, and `cancelled`
    are excluded since there is nothing to navigate to yet or anymore.

    Only returns rows where the slip actually has coordinates set
    (`latitude`/`longitude` are nullable per `alembic/sql/0016...`'s
    comment -- a marina that never populated them has nothing to show
    here, and the frontend should treat an empty list as "no GPS location
    on file for your dock" rather than an error). Filtered by
    `customer_id = :cid` in the SQL itself, not just company_id --
    mirrors every other query in this module (see module docstring's
    isolation-guarantee #2): Customer A's token must never resolve
    Customer B's slip location even within the same tenant.
    """
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT r.id AS reservation_id, r.status, r.start_date, r.end_date,
                           s.id AS slip_id, s.identifier AS slip_identifier,
                           s.latitude, s.longitude
                      FROM slip_reservations r
                      JOIN slips s ON s.id = r.slip_id
                     WHERE r.customer_id = :cid
                       AND r.status IN ('confirmed', 'checked_in')
                       AND s.latitude IS NOT NULL
                       AND s.longitude IS NOT NULL
                     ORDER BY r.start_date DESC
                    """
                ),
                {"cid": customer_id},
            ).all()
        )


def send_portal_invite(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> int:
    """Staff-triggered: issue (or renew) a customer's portal link and queue
    the notification email. Mirrors `invoices.send_invoice`'s exact shape --
    issue token, build the link, `outbox.enqueue`, `db.commit()` -- one
    transaction, caller schedules `dispatch_outbox_soon` after this returns.

    Returns the outbox event id (not the raw token -- callers that need the
    token itself, e.g. tests, call `issue_portal_token` directly).
    """
    with tenant_context(db, company_id):
        customer = db.execute(
            text("SELECT email FROM customers WHERE id = :id"), {"id": customer_id}
        ).first()
        if customer is None:
            db.rollback()
            raise NotFound(f"customer {customer_id} not found")

        raw_token = issue_portal_token(db, company_id, customer_id)
        base_url = settings.app_base_url.rstrip("/")
        portal_url = f"{base_url}/portal/{raw_token}"

        event_id = outbox.enqueue(
            db,
            company_id,
            "customer.portal_invite",
            {
                "customer_id": str(customer_id),
                "customer_email": customer.email,
                "portal_url": portal_url,
            },
        )
        db.commit()
    return event_id


def get_estimate_approve_token(
    db: Session, company_id: uuid.UUID, customer_id: uuid.UUID, estimate_id: uuid.UUID
) -> str | None:
    """Issue a fresh `estimate_approve` token for one of the customer's OWN
    pending estimates, so the portal's "approve" button can hand the SAME
    existing approval flow (`POST /public/estimate/{token}/approve`) a live
    token rather than re-implementing approval. Returns `None` if the
    estimate does not belong to this customer or is not in an approvable
    state — the route maps that to 404, never leaking which case it was.
    """
    from app.services.public_tokens import issue_public_token
    from app.services.state_machines import EstimateSM

    with tenant_context(db, company_id):
        row = db.execute(
            text(
                "SELECT status FROM estimates WHERE id = :id AND customer_id = :cid"
            ),
            {"id": estimate_id, "cid": customer_id},
        ).first()
        if row is None or not EstimateSM.can_transition(row.status, "approved"):
            return None
        return issue_public_token(
            db, company_id, "estimate", estimate_id, "estimate_approve", ttl_hours=72
        )
