"""Stripe Connect onboarding/status + the dunning sweep (Phase 8).

Grouped in one module because both are "billing administration" concerns
gated behind `require_admin`, distinct from `app.services.invoices` (which
owns the invoice lifecycle itself) and `app.services.stripe_billing` (the
only place the `stripe` SDK is imported).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.tenant import tenant_context
from app.services import outbox, stripe_billing
from app.services.crud import NotFound

#: Do not re-remind an invoice more than once per this many days, so a
#: shop's customers are not spammed by an automated sweep run on a tight
#: schedule (cron/CI) while a human is also manually chasing the account.
DUNNING_REMINDER_COOLDOWN_DAYS = 3


# ---------------------------------------------------------------------------
# Stripe Connect
# ---------------------------------------------------------------------------
class ConnectUnavailable(Exception):
    """Raised when Stripe is not configured or the Connect API call fails."""


def start_connect_onboarding(db: Session, company_id: uuid.UUID) -> dict[str, Any]:
    """Create (or resume) Stripe Connect Standard onboarding for a tenant.

    Reuses an existing `stripe_connect_account_id` if onboarding was started
    before but never finished, rather than creating a duplicate account each
    time an admin clicks "Connect Stripe" again.
    """
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT stripe_connect_account_id FROM companies WHERE id = :id"),
            {"id": company_id},
        ).first()
        if row is None:
            raise NotFound(f"company {company_id} not found")

        base_url = settings.app_base_url.rstrip("/")
        result = stripe_billing.create_connect_account_and_onboarding_link(
            company_id,
            existing_account_id=row.stripe_connect_account_id,
            return_url=f"{base_url}/settings/billing?connect=return",
            refresh_url=f"{base_url}/settings/billing?connect=refresh",
        )
        if result is None:
            raise ConnectUnavailable(
                "Stripe is not configured or the Connect API call failed"
            )

        db.execute(
            text(
                "UPDATE companies SET stripe_connect_account_id = :aid WHERE id = :id"
            ),
            {"aid": result["account_id"], "id": company_id},
        )
        db.commit()

    return {"account_id": result["account_id"], "onboarding_url": result["url"]}


def get_connect_status(db: Session, company_id: uuid.UUID) -> dict[str, Any]:
    """Connect status for the settings page. `connected=False` (with no
    Stripe call made) is the normal, fully-supported state for a tenant that
    has never started onboarding."""
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT stripe_connect_account_id FROM companies WHERE id = :id"),
            {"id": company_id},
        ).first()
    if row is None:
        raise NotFound(f"company {company_id} not found")

    if not row.stripe_connect_account_id:
        return {
            "connected": False,
            "account_id": None,
            "charges_enabled": False,
            "details_submitted": False,
        }

    status = stripe_billing.get_connect_account_status(row.stripe_connect_account_id)
    if status is None:
        # Account id on file but Stripe is unreachable/unconfigured right
        # now -- report what we know rather than erroring the whole page.
        return {
            "connected": True,
            "account_id": row.stripe_connect_account_id,
            "charges_enabled": False,
            "details_submitted": False,
        }

    return {
        "connected": True,
        "account_id": row.stripe_connect_account_id,
        "charges_enabled": status["charges_enabled"],
        "details_submitted": status["details_submitted"],
    }


# ---------------------------------------------------------------------------
# Dunning
# ---------------------------------------------------------------------------
def run_dunning_sweep(db: Session, company_id: uuid.UUID) -> dict[str, Any]:
    """Find unpaid invoices past `due_date` and queue a reminder for each,
    respecting `DUNNING_REMINDER_COOLDOWN_DAYS`.

    Callable per-tenant (`POST /billing/dunning/run`, `require_admin`) or in
    a loop over every company by `app/jobs/dunning_sweep.py` (no Celery yet
    -- see that module's docstring). Queues through the existing outbox
    (`invoice.dunning_reminder`) rather than sending email directly, so
    delivery goes through the same claim/retry/dead-letter machinery as
    every other outbound email.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=DUNNING_REMINDER_COOLDOWN_DAYS)

    with tenant_context(db, company_id):
        candidates = db.execute(
            text(
                """
                SELECT i.id, i.customer_id, i.balance_due
                  FROM invoices i
                 WHERE i.company_id = :cid
                   AND i.status IN ('sent', 'partial')
                   AND i.due_date IS NOT NULL
                   AND i.due_date < now()
                   AND i.balance_due > 0
                   AND (i.last_reminder_sent_at IS NULL
                        OR i.last_reminder_sent_at < :cutoff)
                 ORDER BY i.due_date
                 FOR UPDATE
                """
            ),
            {"cid": company_id, "cutoff": cutoff},
        ).all()

        reminded: list[str] = []
        for row in candidates:
            customer_email = None
            if row.customer_id is not None:
                cust = db.execute(
                    text("SELECT email FROM customers WHERE id = :id"),
                    {"id": row.customer_id},
                ).first()
                customer_email = cust.email if cust else None

            pay_url = f"/api/v1/public/invoice/{row.id}"
            outbox.enqueue(
                db,
                company_id,
                "invoice.dunning_reminder",
                {
                    "invoice_id": str(row.id),
                    "customer_email": customer_email,
                    "pay_url": pay_url,
                },
            )
            db.execute(
                text(
                    "UPDATE invoices SET last_reminder_sent_at = now() WHERE id = :id"
                ),
                {"id": row.id},
            )
            reminded.append(str(row.id))

        db.commit()

    return {"reminded_invoice_ids": reminded, "count": len(reminded)}


__all__ = [
    "ConnectUnavailable",
    "DUNNING_REMINDER_COOLDOWN_DAYS",
    "get_connect_status",
    "run_dunning_sweep",
    "start_connect_onboarding",
]
