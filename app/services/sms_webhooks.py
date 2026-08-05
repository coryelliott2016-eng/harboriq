"""Inbound SMS webhook handling (Phase 11).

Twilio (or any provider speaking its form-encoded webhook convention) POSTs
here whenever someone texts the shop's number. This is a PUBLIC,
unauthenticated platform endpoint exactly like `/webhooks/stripe` — there is
no tenant context until we resolve one, so every lookup here uses the
SERVICE session (BYPASSRLS), matching `app.services.stripe_webhooks`.

Company resolution: Twilio does not tell us which tenant a message belongs
to (a shop's Twilio number is not modeled anywhere yet — that is Phase 12
multi-number support). For this phase we resolve purely by matching the
`From` number against `customers.phone` across ALL tenants. This is safe
only because phone numbers are not tenant-shared today; if two tenants ever
share a customer's phone number (e.g. after Phase 12 onboarding evolves),
this resolution strategy will need a proper per-company Twilio number
mapping. Documented in the README as a known Phase-11 simplification.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import messages

logger = logging.getLogger("harboriq.sms")


def verify_twilio_signature(url: str, params: dict[str, Any], signature: str | None) -> bool:
    """Validate `X-Twilio-Signature` per Twilio's documented algorithm:
    HMAC-SHA1 of (URL + each POST param key/value, sorted and concatenated),
    keyed by the auth token, base64-encoded.

    Returns True when Twilio is not configured at all (`settings.
    twilio_auth_token` unset) — there is nothing to check against, and the
    caller is expected to log a warning in that case (this function only
    computes; `receive_inbound_sms` decides what "unconfigured" means for
    the request as a whole).
    """
    if not settings.twilio_auth_token:
        return True
    if not signature:
        return False

    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(
        settings.twilio_auth_token.encode(), data.encode(), hashlib.sha1
    ).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def _find_customer_by_phone(db: Session, phone: str):
    """Resolve `(company_id, customer_id)` for an inbound phone number,
    across every tenant (service/BYPASSRLS session — see module docstring).
    """
    return db.execute(
        text(
            """
            SELECT company_id, id AS customer_id
              FROM customers
             WHERE phone = :phone
             ORDER BY created_at DESC
             LIMIT 1
            """
        ),
        {"phone": phone},
    ).first()


def receive_inbound_sms(
    db: Session, *, from_number: str, body: str
) -> dict[str, Any]:
    """Handle one inbound SMS. Always returns a small status dict; never
    raises for a business-level "no match" — an unmatched number is logged
    and dropped (documented choice: storing an orphan message with no
    customer/company to scope it to would violate every other table's
    tenant-scoping invariant, and there is no per-tenant "unknown senders"
    inbox yet to put it in).
    """
    match = _find_customer_by_phone(db, from_number)
    if match is None:
        logger.warning("inbound sms from unmatched number=%s dropped", from_number)
        return {"status": "unmatched", "customer_id": None}

    company_id = match.company_id
    customer_id = match.customer_id
    # `send_from_customer` opens its own `tenant_context` internally (same
    # service function the customer portal uses) — nesting one here would
    # just re-set the same session variable redundantly.
    row = messages.send_from_customer(
        db, company_id, customer_id, body, channel="sms"
    )
    return {
        "status": "matched",
        "company_id": str(company_id),
        "customer_id": str(customer_id),
        "message_id": str(row.id),
    }
