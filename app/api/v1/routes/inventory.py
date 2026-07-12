import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import current_company_id, get_db
from app.schemas.inventory import UsePartRequest, UsePartResponse
from app.services.inventory import InsufficientStock, use_inventory_part_atomic

router = APIRouter()


@router.post("/inventory/use", response_model=UsePartResponse)
def use_part(
    body: UsePartRequest,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(current_company_id),
):
    """Atomic, concurrency-safe stock deduction."""
    try:
        remaining = use_inventory_part_atomic(db, company_id, uuid.UUID(body.item_id), body.quantity)
    except InsufficientStock:
        raise HTTPException(status_code=409, detail="insufficient stock")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UsePartResponse(item_id=body.item_id, remaining_on_hand=remaining)
