"""Company-level settings (Phase 17, Area C.2): the admin-forced MFA policy.

Deliberately narrow -- this is not a general company-profile CRUD module
(there is no broader "edit company name/slug" surface yet), just the one
new toggle this phase adds. A future phase that grows company settings
further should probably absorb this into a proper `CompanySettingsUpdate`
schema rather than bolting more single-purpose functions on here.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import NotFound


def get_mfa_policy(db: Session, company_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT id, mfa_required FROM companies WHERE id = :id"),
            {"id": company_id},
        ).first()
    if row is None:
        raise NotFound(f"company {company_id} not found")
    return row


def set_mfa_required(db: Session, company_id: uuid.UUID, *, required: bool) -> Row:
    """Admin-only (enforced at the route layer via `require_admin`).

    Taking effect is immediate for the NEXT login attempt of any user
    without MFA enrolled (see `app.services.auth.login`'s
    `company_mfa_required` branch) -- it does not retroactively invalidate
    already-issued sessions, consistent with how every other
    permission/role change in this codebase behaves (see `app/api/deps.py`
    module docstring: role changes take effect on the next request that
    re-reads the database row, not via token revocation).
    """
    with tenant_context(db, company_id):
        row = db.execute(
            text(
                """
                UPDATE companies
                   SET mfa_required = :required, updated_at = now()
                 WHERE id = :id
                RETURNING id, mfa_required
                """
            ),
            {"required": required, "id": company_id},
        ).first()
        db.commit()
    if row is None:
        raise NotFound(f"company {company_id} not found")
    return row


__all__ = ["get_mfa_policy", "set_mfa_required"]
