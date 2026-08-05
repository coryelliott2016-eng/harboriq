"""Company-level settings (Phase 17, Area C.2): admin-forced MFA policy.

`GET /companies/me/mfa-policy` — any authenticated user may check whether
their company currently mandates MFA (useful for a frontend banner
prompting unenrolled users to set it up before they get locked out).

`PATCH /companies/me/mfa-policy` — owner/admin only. Toggling this on
does not retroactively affect already-issued sessions; see
`app.services.companies.set_mfa_required`'s docstring.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_admin
from app.schemas.auth import CompanyMfaPolicyOut, CompanyMfaPolicyUpdate
from app.services import companies as companies_service

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/me/mfa-policy", response_model=CompanyMfaPolicyOut)
def get_mfa_policy(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    row = companies_service.get_mfa_policy(db, company_id)
    return CompanyMfaPolicyOut(mfa_required=row.mfa_required)


@router.patch(
    "/me/mfa-policy",
    response_model=CompanyMfaPolicyOut,
    dependencies=[Depends(require_admin)],
)
def update_mfa_policy(
    body: CompanyMfaPolicyUpdate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    row = companies_service.set_mfa_required(db, company_id, required=body.mfa_required)
    return CompanyMfaPolicyOut(mfa_required=row.mfa_required)
