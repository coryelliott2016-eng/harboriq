"""Slip CRUD endpoints (Phase 15).

All mutating routes are `require_operations`-gated, same as `vendors.py` --
managing marina infrastructure is an operations action, not something a
field technician's read-mostly role needs.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.slips import SlipCreate, SlipOut, SlipUpdate
from app.services import slips as service

router = APIRouter(prefix="/slips", tags=["slips"])


@router.post(
    "",
    response_model=SlipOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_slip(
    body: SlipCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.create(db, company_id, body.model_dump())


@router.get("", response_model=list[SlipOut])
def list_slips(
    slip_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.list_slips(
        db, company_id, slip_type=slip_type, status=status_filter, search=search
    )


@router.get("/{slip_id}", response_model=SlipOut)
def get_slip(
    slip_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.get(db, company_id, slip_id)


@router.patch(
    "/{slip_id}",
    response_model=SlipOut,
    dependencies=[Depends(require_operations)],
)
def update_slip(
    slip_id: uuid.UUID,
    body: SlipUpdate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.update(
            db, company_id, slip_id, body.model_dump(exclude_unset=True)
        )
