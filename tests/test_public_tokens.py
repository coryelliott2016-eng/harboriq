"""Public tokens — issue + approve in one transaction; expiry/scope/revocation."""
from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import text

from app.services.public_tokens import (
    InvalidToken,
    approve_estimate_with_token,
    issue_public_token,
    revoke_public_token,
)
from app.services.state_machines import IllegalTransition
from tests.conftest import make_estimate


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def test_issue_and_approve_estimate(service_db, company_a):
    est = make_estimate(service_db, company_a, status="sent")
    token = issue_public_token(
        service_db, company_a, "estimate", est, "estimate_approve", ttl_hours=1
    )

    result = approve_estimate_with_token(
        service_db, token, ip="203.0.113.7", user_agent="TestUA/1.0",
        estimate_pdf_version="v1",
    )
    assert result["estimate_id"] == str(est)

    row = service_db.execute(
        text("SELECT status, approved_ip, estimate_pdf_version FROM estimates WHERE id=:id"),
        {"id": est},
    ).first()
    assert row.status == "approved"
    assert str(row.approved_ip) == "203.0.113.7"
    assert row.estimate_pdf_version == "v1"

    tok = service_db.execute(
        text("SELECT uses FROM public_tokens WHERE token_hash = :h"),
        {"h": _hash(token)},
    ).first()
    assert tok.uses == 1


def test_expired_token_rejected(service_db, company_a):
    est = make_estimate(service_db, company_a, status="sent")
    token = issue_public_token(
        service_db, company_a, "estimate", est, "estimate_approve", ttl_hours=1
    )
    service_db.execute(
        text("UPDATE public_tokens SET expires_at = now() - interval '1 hour'")
    )
    service_db.commit()

    with pytest.raises(InvalidToken):
        approve_estimate_with_token(service_db, token, "1.1.1.1", "UA", "v1")


def test_wrong_purpose_rejected(service_db, company_a):
    est = make_estimate(service_db, company_a, status="sent")
    token = issue_public_token(
        service_db, company_a, "estimate", est, "invoice_pay", ttl_hours=1
    )
    with pytest.raises(InvalidToken):
        approve_estimate_with_token(service_db, token, "1.1.1.1", "UA", "v1")


def test_revoked_token_rejected(service_db, company_a):
    est = make_estimate(service_db, company_a, status="sent")
    token = issue_public_token(
        service_db, company_a, "estimate", est, "estimate_approve", ttl_hours=1
    )
    revoke_public_token(service_db, _hash(token))

    with pytest.raises(InvalidToken):
        approve_estimate_with_token(service_db, token, "1.1.1.1", "UA", "v1")


def test_failed_approval_does_not_burn_token(service_db, company_a):
    """Approving an already-approved estimate raises IllegalTransition, but the
    token is NOT consumed (uses stays 0)."""
    est = make_estimate(service_db, company_a, status="approved")  # already approved
    token = issue_public_token(
        service_db, company_a, "estimate", est, "estimate_approve", ttl_hours=1
    )

    with pytest.raises(IllegalTransition):
        approve_estimate_with_token(service_db, token, "1.1.1.1", "UA", "v1")

    tok = service_db.execute(
        text("SELECT uses FROM public_tokens WHERE token_hash = :h"),
        {"h": _hash(token)},
    ).first()
    assert tok.uses == 0
