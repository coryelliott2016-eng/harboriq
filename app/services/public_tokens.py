"""Public access tokens — issue + verify for the customer portal.

Security model:
  * 256-bit entropy (secrets.token_urlsafe(32))
  * store only SHA-256(token) — DB compromise cannot recover live tokens
  * expiry, scope (purpose), use-limit, revocation
  * audit log on every use; estimate approvals record IP/UA + pdf version
  * tenant resolved FROM the token via the service role, then the actual
    action runs inside tenant_context so RLS applies

Approval is a SINGLE transaction: verify token (FOR UPDATE) -> transition
estimate -> audit -> commit. If the transition fails the token is not burned.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.state_machines import EstimateSM

TOKEN_BYTES = 32  # 256-bit entropy (>=128 required)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_public_token(
    db: Session,
    company_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    purpose: str,
    ttl_hours: int = 72,
    max_uses: int = 1,
) -> str:
    """Create a scoped, expiring token. Returns the raw token ONCE."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    with tenant_context(db, company_id):
        db.execute(
            text(
                """
                INSERT INTO public_tokens
                    (company_id, resource_type, resource_id, purpose,
                     token_hash, expires_at, max_uses)
                VALUES (:cid, :rt, :rid, :p, :th, :exp, :mu)
                """
            ),
            {
                "cid": company_id,
                "rt": resource_type,
                "rid": resource_id,
                "p": purpose,
                "th": _hash(raw),
                "exp": datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
                "mu": max_uses,
            },
        )
        db.commit()
    return raw


class InvalidToken(Exception):
    pass


class IllegalApproval(Exception):
    pass


def approve_estimate_with_token(
    db: Session,
    raw_token: str,
    ip: str,
    user_agent: str,
    estimate_pdf_version: str,
) -> dict:
    """Resolve token (service role) -> approve estimate (tenant context) in ONE tx.

    The token is only consumed (uses incremented) if the approval succeeds.
    Returns {"company_id", "estimate_id"}.
    """
    token_hash = _hash(raw_token)

    # Step 1: service-role global lookup (BYPASSRLS) — lock the token row.
    token_row = db.execute(
        text(
            """
            SELECT id, company_id, resource_type, resource_id, purpose,
                   expires_at, max_uses, uses, revoked_at
              FROM public_tokens
             WHERE token_hash = :th
               AND revoked_at IS NULL
               AND expires_at > now()
               AND uses < max_uses
             FOR UPDATE
            """
        ),
        {"th": token_hash},
    ).first()

    if token_row is None:
        raise InvalidToken("token not found, expired, revoked, or exhausted")
    if token_row.purpose != "estimate_approve":
        raise InvalidToken("token scope mismatch")
    if token_row.resource_type != "estimate":
        raise InvalidToken("token resource type mismatch")

    company_id = token_row.company_id

    # Step 2: tenant-scoped work (RLS applies). Everything below commits or
    # rolls back together — a failed transition does NOT burn the token.
    with tenant_context(db, company_id):
        estimate_id = token_row.resource_id

        est_row = db.execute(
            text("SELECT status FROM estimates WHERE id = :id FOR UPDATE"),
            {"id": estimate_id},
        ).first()
        if est_row is None:
            raise InvalidToken("estimate not found in this tenant")

        EstimateSM.assert_transition(est_row.status, "approved")

        db.execute(
            text(
                """
                UPDATE estimates
                   SET status = 'approved',
                       approved_at = now(),
                       approved_ip = :ip,
                       approved_user_agent = :ua,
                       estimate_pdf_version = :ver
                 WHERE id = :id
                """
            ),
            {"ip": ip, "ua": user_agent, "ver": estimate_pdf_version, "id": estimate_id},
        )

        # Consume the token only after the approval succeeded.
        db.execute(
            text("UPDATE public_tokens SET uses = uses + 1 WHERE id = :id"),
            {"id": token_row.id},
        )

        db.execute(
            text(
                """
                INSERT INTO audit_log
                    (company_id, action, resource_type, resource_id, metadata)
                VALUES (:cid, 'estimate.approved', 'estimate', :id,
                        jsonb_build_object('ip', CAST(:ip AS text),
                                           'ua', CAST(:ua AS text),
                                           'version', CAST(:ver AS text)))
                """
            ),
            {
                "cid": company_id,
                "id": estimate_id,
                "ip": ip,
                "ua": user_agent,
                "ver": estimate_pdf_version,
            },
        )
        db.commit()

    return {"company_id": str(company_id), "estimate_id": str(estimate_id)}


def resolve_read_only_token(
    db: Session, raw_token: str, purpose: str, resource_type: str
) -> dict:
    """Resolve a token WITHOUT consuming a use.

    For actions that only ever read state (e.g. loading an invoice pay page)
    rather than performing a one-shot mutation. A customer may reload that
    page many times before completing Stripe checkout, and the actual state
    change happens via webhook — not via this lookup — so `uses` must stay
    untouched here. Still validates expiry/revocation/use-limit/scope exactly
    like `approve_estimate_with_token`; it just never issues the `UPDATE
    public_tokens SET uses = uses + 1` that a consuming action would.
    """
    token_hash = _hash(raw_token)

    token_row = db.execute(
        text(
            """
            SELECT id, company_id, resource_type, resource_id, purpose,
                   expires_at, max_uses, uses, revoked_at
              FROM public_tokens
             WHERE token_hash = :th
               AND revoked_at IS NULL
               AND expires_at > now()
               AND uses < max_uses
            """
        ),
        {"th": token_hash},
    ).first()

    if token_row is None:
        raise InvalidToken("token not found, expired, revoked, or exhausted")
    if token_row.purpose != purpose:
        raise InvalidToken("token scope mismatch")
    if token_row.resource_type != resource_type:
        raise InvalidToken("token resource type mismatch")

    return {"company_id": token_row.company_id, "resource_id": token_row.resource_id}


def revoke_public_token(db: Session, token_hash: str) -> None:
    """Admin revocation."""
    db.execute(
        text("UPDATE public_tokens SET revoked_at = now() WHERE token_hash = :th"),
        {"th": token_hash},
    )
    db.commit()
