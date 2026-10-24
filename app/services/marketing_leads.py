"""Platform marketing lead capture (public GTM / trial signup).

Uses the service DB role (BYPASSRLS) because `marketing_leads` is a
platform table with no tenant_id — see migration 0023.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import email as email_service

logger = logging.getLogger("harboriq.marketing_leads")

DUPLICATE_WINDOW = timedelta(hours=24)
EMAIL_MARKETING_CONSENT_VERSION = "2026-10-01-v1"

LEAD_COLUMNS = """id, full_name, business_name, email, team_size, source,
    industry, business_need, product_interest, email_marketing_opt_in, contact_requested,
    email_marketing_consented_at, email_marketing_consent_version, notified_at, created_at"""


def _classified(row) -> dict:
    lead = dict(row)
    lead["classification"] = f"{lead['industry']}:{lead['product_interest']}"
    return lead

TEAM_SIZE_LABELS = {
    "solo": "Just me (Solo)",
    "team": "2–5 people (Team)",
    "business": "6–15 people (Business)",
    "enterprise": "16+ people (Enterprise)",
}


def find_recent_duplicate(
    db: Session, email: str, *, industry: str = "other", business_need: str = "",
    product_interest: str = "operations", email_marketing_opt_in: bool = False,
    contact_requested: bool = True,
) -> dict | None:
    """De-duplicate the latest submission only when classification and permissions match."""
    cutoff = datetime.now(timezone.utc) - DUPLICATE_WINDOW
    row = db.execute(
        text(
            f"""
            SELECT {LEAD_COLUMNS}
            FROM marketing_leads
            WHERE lower(email::text) = lower(:email)
              AND created_at >= :cutoff
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"email": email, "cutoff": cutoff},
    ).mappings().first()
    expected = {
        "industry": industry, "business_need": business_need,
        "product_interest": product_interest, "email_marketing_opt_in": email_marketing_opt_in,
        "contact_requested": contact_requested,
    }
    if row and all(row[key] == value for key, value in expected.items()):
        return _classified(row)
    return None


def create_lead(
    db: Session,
    *,
    full_name: str,
    business_name: str,
    email: str,
    team_size: str,
    source: str,
    ip_hint: str | None,
    user_agent: str | None,
    industry: str = "other",
    business_need: str = "",
    product_interest: str = "operations",
    email_marketing_opt_in: bool = False,
    contact_requested: bool = True,
) -> dict:
    """Insert a marketing lead. Caller commits."""
    # Explicit casts on every parameter so psycopg's server-side type
    # inference doesn't blow up on NULL (AmbiguousParameter on $6/inet).
    # CAST(NULL AS inet) is well-defined; CAST('' AS inet) is not — the
    # caller normalises empty strings to None above.
    row = db.execute(
        text(
            f"""
            INSERT INTO marketing_leads (
                full_name, business_name, email, team_size, source,
                ip_hint, user_agent, industry, business_need, product_interest,
                email_marketing_opt_in, contact_requested,
                email_marketing_consented_at, email_marketing_consent_version
            )
            VALUES (
                CAST(:full_name AS text),
                CAST(:business_name AS text),
                CAST(:email AS citext),
                CAST(:team_size AS text),
                CAST(:source AS text),
                CAST(:ip_hint AS inet),
                CAST(:user_agent AS text),
                CAST(:industry AS text), CAST(:business_need AS text),
                CAST(:product_interest AS text), CAST(:email_marketing_opt_in AS boolean),
                CAST(:contact_requested AS boolean),
                CAST(:email_marketing_consented_at AS timestamptz),
                CAST(:email_marketing_consent_version AS text)
            )
            RETURNING {LEAD_COLUMNS}
            """
        ),
        {
            "full_name": full_name,
            "business_name": business_name,
            "email": email,
            "team_size": team_size,
            "source": source or "marketing-signup",
            "ip_hint": ip_hint or None,
            "user_agent": (user_agent or "")[:500] or None,
            "industry": industry,
            "business_need": business_need,
            "product_interest": product_interest,
            "email_marketing_opt_in": email_marketing_opt_in,
            "contact_requested": contact_requested,
            "email_marketing_consented_at": datetime.now(timezone.utc) if email_marketing_opt_in else None,
            "email_marketing_consent_version": EMAIL_MARKETING_CONSENT_VERSION if email_marketing_opt_in else None,
        },
    ).mappings().one()
    return _classified(row)


def mark_notified(db: Session, lead_id: uuid.UUID) -> None:
    db.execute(
        text(
            """
            UPDATE marketing_leads
            SET notified_at = now()
            WHERE id = :id
            """
        ),
        {"id": lead_id},
    )


def list_leads(db: Session, *, limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 500))
    rows = db.execute(
        text(
            f"""
            SELECT {LEAD_COLUMNS}
            FROM marketing_leads
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return [_classified(r) for r in rows]


def notify_new_lead(lead: dict) -> bool:
    """Send internal notification email. Never raises."""
    to = (settings.marketing_lead_notify_to or "").strip()
    if not to:
        logger.info("marketing_lead.notify_skipped_no_recipient id=%s", lead.get("id"))
        return False

    team_label = TEAM_SIZE_LABELS.get(lead.get("team_size", ""), lead.get("team_size", ""))
    contact_permission = (
        "Requested follow-up contact allowed; email marketing consent is separate."
        if lead.get("contact_requested", True)
        else "No permission to contact for sales/demo follow-up; do not send unsolicited follow-up."
    )
    subject = f"[HarborIQ] New trial signup — {lead.get('business_name', 'unknown')}"
    body = (
        "New HarborIQ marketing signup\n"
        "================================\n"
        f"Name:     {lead.get('full_name')}\n"
        f"Business: {lead.get('business_name')}\n"
        f"Email:    {lead.get('email')}\n"
        f"Team:     {team_label}\n"
        f"Source:   {lead.get('source')}\n"
        f"Industry: {lead.get('industry')}\n"
        f"Interest: {lead.get('product_interest')}\n"
        f"Routing:  {lead.get('classification')}\n"
        f"Need (untrusted user text): {lead.get('business_need')}\n"
        f"Contact requested: {lead.get('contact_requested')}\n"
        f"Contact permission: {contact_permission}\n"
        f"Email marketing opt-in: {lead.get('email_marketing_opt_in')}\n"
        f"Consent timestamp: {lead.get('email_marketing_consented_at')}\n"
        f"Consent version: {lead.get('email_marketing_consent_version')}\n"
        "Internal routing only. No automated marketing or partner sharing authorized.\n"
        f"Lead ID:  {lead.get('id')}\n"
        f"Created:  {lead.get('created_at')}\n"
    )
    try:
        return email_service.send_email(to=to, subject=subject, text_body=body)
    except Exception:  # noqa: BLE001 — never fail the request path
        logger.exception("marketing_lead.notify_failed id=%s", lead.get("id"))
        return False
