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

TEAM_SIZE_LABELS = {
    "solo": "Just me (Solo)",
    "team": "2–5 people (Team)",
    "business": "6–15 people (Business)",
    "enterprise": "16+ people (Enterprise)",
}
MARKETING_EMAIL_CONSENT_VERSION = "marketing-email-v1"
MARKETING_EMAIL_CONSENT_METHOD = "public-lead-form"


def find_recent_duplicate(db: Session, email: str) -> dict | None:
    """Return the most recent lead for this email within 24h, if any."""
    cutoff = datetime.now(timezone.utc) - DUPLICATE_WINDOW
    row = db.execute(
        text(
            """
            SELECT id, full_name, business_name, email, team_size, source,
                   marketing_email_opt_in, marketing_email_consent_at,
                   marketing_email_consent_version, marketing_email_consent_method,
                   notified_at, created_at
            FROM marketing_leads
            WHERE lower(email::text) = lower(:email)
              AND created_at >= :cutoff
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"email": email, "cutoff": cutoff},
    ).mappings().first()
    return dict(row) if row else None


def create_lead(
    db: Session,
    *,
    full_name: str,
    business_name: str,
    email: str,
    team_size: str,
    source: str,
    marketing_email_opt_in: bool,
) -> dict:
    """Insert a marketing lead. Caller commits."""
    row = db.execute(
        text(
            """
            INSERT INTO marketing_leads (
                full_name, business_name, email, team_size, source, marketing_email_opt_in,
                marketing_email_consent_at, marketing_email_consent_version,
                marketing_email_consent_method
            )
            VALUES (
                CAST(:full_name AS text),
                CAST(:business_name AS text),
                CAST(:email AS citext),
                CAST(:team_size AS text),
                CAST(:source AS text),
                :marketing_email_opt_in,
                CASE WHEN :marketing_email_opt_in THEN now() END,
                CASE WHEN :marketing_email_opt_in THEN :consent_version END,
                CASE WHEN :marketing_email_opt_in THEN :consent_method END
            )
            RETURNING id, full_name, business_name, email, team_size, source,
                      marketing_email_opt_in, marketing_email_consent_at,
                      marketing_email_consent_version, marketing_email_consent_method,
                      notified_at, created_at
            """
        ),
        {
            "full_name": full_name,
            "business_name": business_name,
            "email": email,
            "team_size": team_size,
            "source": source or "marketing-signup",
            "marketing_email_opt_in": marketing_email_opt_in,
            "consent_version": MARKETING_EMAIL_CONSENT_VERSION,
            "consent_method": MARKETING_EMAIL_CONSENT_METHOD,
        },
    ).mappings().one()
    return dict(row)


def record_marketing_email_consent(db: Session, lead_id: uuid.UUID) -> None:
    """Record new affirmative permission without resetting existing evidence."""
    db.execute(
        text(
            """
            UPDATE marketing_leads
            SET marketing_email_opt_in = true,
                marketing_email_consent_at = now(),
                marketing_email_consent_version = :consent_version,
                marketing_email_consent_method = :consent_method
            WHERE id = :id
              AND NOT marketing_email_opt_in
            """
        ),
        {
            "id": lead_id,
            "consent_version": MARKETING_EMAIL_CONSENT_VERSION,
            "consent_method": MARKETING_EMAIL_CONSENT_METHOD,
        },
    )


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
            """
            SELECT id, full_name, business_name, email, team_size, source,
                   marketing_email_opt_in, marketing_email_consent_at,
                   marketing_email_consent_version, marketing_email_consent_method,
                   notified_at, created_at
            FROM marketing_leads
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def notify_new_lead(lead: dict) -> bool:
    """Send internal notification email. Never raises."""
    to = (settings.marketing_lead_notify_to or "").strip()
    if not to:
        logger.info("marketing_lead.notify_skipped_no_recipient id=%s", lead.get("id"))
        return False

    team_label = TEAM_SIZE_LABELS.get(lead.get("team_size", ""), lead.get("team_size", ""))
    subject = f"[HarborIQ] New trial signup — {lead.get('business_name', 'unknown')}"
    body = (
        "New HarborIQ marketing signup\n"
        "================================\n"
        f"Name:     {lead.get('full_name')}\n"
        f"Business: {lead.get('business_name')}\n"
        f"Email:    {lead.get('email')}\n"
        f"Team:     {team_label}\n"
        f"Source:   {lead.get('source')}\n"
        f"Marketing email consent: "
        f"{'Yes' if lead.get('marketing_email_opt_in') else 'No'}\n"
        f"Lead ID:  {lead.get('id')}\n"
        f"Created:  {lead.get('created_at')}\n"
    )
    try:
        return email_service.send_email(to=to, subject=subject, text_body=body)
    except Exception:  # noqa: BLE001 — never fail the request path
        logger.exception("marketing_lead.notify_failed id=%s", lead.get("id"))
        return False
