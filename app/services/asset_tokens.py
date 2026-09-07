"""Draft-only asset-token registration (Phase 19).

This service intentionally contains creation and tenant-scoped read paths
only. Migration 0021's `CHECK (status = 'draft')` prevents any future caller
from changing a record's status without an explicit, reviewed schema change.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import NotFound, ValidationFailed

ASSET_TOKEN_TYPES = frozenset({"vessel", "slip", "equipment", "receivable"})


def _require_vessel(db: Session, vessel_id: uuid.UUID) -> None:
    """Require a vessel visible to the active tenant before recording it."""
    exists = db.execute(
        text("SELECT 1 FROM vessels WHERE id = :id"),
        {"id": vessel_id},
    ).first()
    if exists is None:
        raise NotFound(f"vessel {vessel_id} not found")


def register_draft_asset_token(
    db: Session,
    company_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    asset_type: str,
    vessel_id: uuid.UUID | None,
    source_description: str,
    estimated_value: Decimal | None,
    notes: str | None,
) -> dict[str, Row[Any]]:
    """Register one asset-tokenization intent and its immutable registration entry.

    This function deliberately accepts no status argument. `asset_tokens.status`
    is omitted from the INSERT so its database default and hard CHECK
    constraint are the sole authority for its only permitted value: `draft`.
    """
    if asset_type not in ASSET_TOKEN_TYPES:
        raise ValidationFailed(f"unsupported asset token type: {asset_type}")
    if asset_type == "vessel" and vessel_id is None:
        raise ValidationFailed("vessel_id is required when asset_type is vessel")

    with tenant_context(db, company_id):
        # Validate every supplied vessel reference up front. For vessel assets
        # this is required domain validation; for the optional reference on
        # other asset types it turns a tenant-mismatched composite FK into the
        # same non-leaking 404.
        if vessel_id is not None:
            _require_vessel(db, vessel_id)

        asset_token = db.execute(
            text(
                """
                INSERT INTO asset_tokens
                    (company_id, asset_type, vessel_id, source_description,
                     estimated_value, notes, created_by)
                VALUES
                    (:company_id, CAST(:asset_type AS asset_token_type), :vessel_id,
                     :source_description, :estimated_value, :notes, :created_by)
                RETURNING *
                """
            ),
            {
                "company_id": company_id,
                "asset_type": asset_type,
                "vessel_id": vessel_id,
                "source_description": source_description,
                "estimated_value": estimated_value,
                "notes": notes,
                "created_by": created_by_user_id,
            },
        ).first()
        ledger_entry = db.execute(
            text(
                """
                INSERT INTO token_ledger_entries
                    (asset_token_id, company_id, entry_type, notes)
                VALUES
                    (:asset_token_id, :company_id, 'registered', :notes)
                RETURNING *
                """
            ),
            {
                "asset_token_id": asset_token.id,
                "company_id": company_id,
                "notes": notes,
            },
        ).first()
        db.commit()

    return {"asset_token": asset_token, "ledger_entry": ledger_entry}


def get_asset_token(
    db: Session,
    company_id: uuid.UUID,
    asset_token_id: uuid.UUID,
) -> Row[Any]:
    """Return one draft-only registration, without cross-tenant disclosure."""
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM asset_tokens WHERE id = :id"),
            {"id": asset_token_id},
        ).first()
    if row is None:
        raise NotFound(f"asset token {asset_token_id} not found")
    return row


def list_asset_tokens(db: Session, company_id: uuid.UUID) -> list[Row[Any]]:
    """List only the caller tenant's draft-registration records."""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT *
                      FROM asset_tokens
                     WHERE company_id = :company_id
                     ORDER BY created_at DESC, id DESC
                    """
                ),
                {"company_id": company_id},
            ).all()
        )
