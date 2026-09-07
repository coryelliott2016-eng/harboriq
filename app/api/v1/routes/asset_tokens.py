"""Admin-only, draft-only asset-token registration endpoints (Phase 19).

Pending outside securities-counsel review, this router has no mutation,
issuance, ownership, transfer, or trading endpoint. Migration 0021 enforces
draft-only status at the database level with `CHECK (status = 'draft')`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_company_id,
    get_current_user,
    get_db,
    require_admin,
)
from app.api.errors import http_errors
from app.core.config import settings
from app.schemas.asset_tokens import (
    AssetTokenOut,
    AssetTokenRegistrationCreate,
    AssetTokenRegistrationResponse,
    TokenLedgerEntryOut,
)
from app.services import asset_tokens as service
from app.services.auth import AuthenticatedUser

router = APIRouter(prefix="/asset-tokens", tags=["asset-tokens"])


@router.post(
    "",
    response_model=AssetTokenRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def register_asset_token(
    body: AssetTokenRegistrationCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Record a single draft registration intent and its registered ledger entry."""
    if not settings.asset_tokenization_enabled:
        raise HTTPException(status_code=404, detail="asset tokenization is not enabled")
    with http_errors():
        result = service.register_draft_asset_token(
            db,
            company_id,
            current_user.id,
            body.asset_type,
            body.vessel_id,
            body.source_description,
            body.estimated_value,
            body.notes,
        )
    return AssetTokenRegistrationResponse(
        asset_token=AssetTokenOut.model_validate(result["asset_token"]),
        ledger_entry=TokenLedgerEntryOut.model_validate(result["ledger_entry"]),
    )


@router.get(
    "",
    response_model=list[AssetTokenOut],
    dependencies=[Depends(require_admin)],
)
def list_asset_tokens(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """List this tenant's draft-registration records."""
    return [
        AssetTokenOut.model_validate(row)
        for row in service.list_asset_tokens(db, company_id)
    ]


@router.get(
    "/{asset_token_id}",
    response_model=AssetTokenOut,
    dependencies=[Depends(require_admin)],
)
def get_asset_token(
    asset_token_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Read one tenant-scoped draft registration without leaking other tenants."""
    with http_errors():
        row = service.get_asset_token(db, company_id, asset_token_id)
    return AssetTokenOut.model_validate(row)
