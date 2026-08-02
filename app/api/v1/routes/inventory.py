import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import authorize_job_action, get_current_user, get_db
from app.api.errors import http_errors
from app.schemas.inventory import UsePartRequest, UsePartResponse
from app.services.auth import AuthenticatedUser
from app.services.inventory import InsufficientStock, use_inventory_part_atomic

router = APIRouter()


@router.post("/inventory/use", response_model=UsePartResponse)
def use_part(
    body: UsePartRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Atomic, concurrency-safe stock deduction. Tenant comes from the access token.

    With `job_id`, the part is billed to that work order in the same
    transaction, and the caller must be entitled to touch that job.
    """
    if body.job_id is not None:
        authorize_job_action(db, user, body.job_id)
    try:
        with http_errors():
            remaining = use_inventory_part_atomic(
                db,
                user.company_id,
                uuid.UUID(body.item_id),
                body.quantity,
                job_id=body.job_id,
            )
    except InsufficientStock:
        raise HTTPException(status_code=409, detail="insufficient stock")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UsePartResponse(item_id=body.item_id, remaining_on_hand=remaining)
