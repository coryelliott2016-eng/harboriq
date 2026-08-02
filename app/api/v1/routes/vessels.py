"""Vessel endpoints.

A vessel is reachable two ways: flat under `/vessels?customer_id=...` and
nested under `/customers/{id}/vessels`. Both hit the same service; the nested
form additionally 404s for an unknown customer instead of returning an empty
list.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.vessels import VesselCreate, VesselOut, VesselUpdate
from app.services import vessels as service

router = APIRouter(prefix="/vessels", tags=["vessels"])


@router.post(
    "",
    response_model=VesselOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_vessel(
    body: VesselCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Register a boat against a customer. 404 if the customer is not in this tenant."""
    with http_errors():
        return service.create(db, company_id, body.model_dump())


@router.get("", response_model=list[VesselOut])
def list_vessels(
    customer_id: uuid.UUID | None = None,
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """List the fleet. `search` matches name, make, model, hull id or slip."""
    return service.list_vessels(
        db,
        company_id,
        customer_id=customer_id,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/{vessel_id}", response_model=VesselOut)
def get_vessel(
    vessel_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.get(db, company_id, vessel_id)


@router.patch(
    "/{vessel_id}",
    response_model=VesselOut,
    dependencies=[Depends(require_operations)],
)
def update_vessel(
    vessel_id: uuid.UUID,
    body: VesselUpdate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.update(
            db, company_id, vessel_id, body.model_dump(exclude_unset=True)
        )


@router.delete(
    "/{vessel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_operations)],
)
def delete_vessel(
    vessel_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Delete a vessel. 409 while work orders still reference it."""
    with http_errors():
        service.delete(db, company_id, vessel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
