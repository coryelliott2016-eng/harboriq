import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    authorize_job_action,
    get_current_company_id,
    get_current_user,
    get_db,
    require_operations,
)
from app.api.errors import http_errors
from app.schemas.inventory import (
    GeneratePORequest,
    InventoryItemCreate,
    InventoryItemOut,
    InventoryItemUpdate,
    ReorderSuggestion,
    UsePartRequest,
    UsePartResponse,
)
from app.schemas.purchase_orders import PurchaseOrderOut
from app.services import inventory as inventory_service
from app.services import purchase_orders as po_service
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


# ---------------------------------------------------------------------------
# Phase 13: CRUD, SKU lookup, and low-stock reorder suggestions.
#
# Order matters here: `/inventory/lookup` and `/inventory/reorder-suggestions`
# are registered before `/inventory/{item_id}` so FastAPI's first-match
# routing doesn't swallow them as a UUID path param.
# ---------------------------------------------------------------------------
@router.post(
    "/inventory",
    response_model=InventoryItemOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_inventory_item(
    body: InventoryItemCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Register a new inventory item. Starts at zero on-hand -- see
    `app.services.inventory.create`'s docstring for why."""
    with http_errors():
        return inventory_service.create(db, company_id, body.model_dump())


@router.get("/inventory", response_model=list[InventoryItemOut])
def list_inventory_items(
    search: str | None = Query(default=None, max_length=200),
    low_stock_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """List inventory. `low_stock_only=true` returns only items below their
    reorder point (the same set surfaced by `/inventory/reorder-suggestions`,
    without the vendor grouping)."""
    return inventory_service.list_items(
        db,
        company_id,
        search=search,
        low_stock_only=low_stock_only,
        limit=limit,
        offset=offset,
    )


@router.get("/inventory/lookup", response_model=InventoryItemOut)
def lookup_inventory_item_by_sku(
    sku: str = Query(min_length=1, max_length=100),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Barcode-scan-or-type lookup: resolve a SKU straight to its item.

    See the README's "Inventory, parts & vendors" section for the
    `BarcodeDetector` browser-support caveat this endpoint's frontend
    consumer works around.
    """
    with http_errors():
        return inventory_service.lookup_by_sku(db, company_id, sku)


@router.get("/inventory/reorder-suggestions", response_model=list[ReorderSuggestion])
def get_reorder_suggestions(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Items below their reorder point. A SUGGESTION only -- see
    `app.services.inventory.reorder_suggestions`'s docstring: nothing here
    ever submits a real purchase order unattended."""
    return inventory_service.reorder_suggestions(db, company_id)


@router.post(
    "/inventory/reorder-suggestions/generate-po",
    response_model=PurchaseOrderOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def generate_po_from_reorder_suggestions(
    body: GeneratePORequest,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """One-click draft PO from selected low-stock items. Still just a
    `draft` -- a human must call `POST /purchase-orders/{id}/submit` before
    it means anything to the vendor (deliberate scope boundary, not a gap)."""
    with http_errors():
        return po_service.generate_draft_from_suggestions(
            db, company_id, user.id, body.vendor_id, body.item_ids
        )


@router.get("/inventory/{item_id}", response_model=InventoryItemOut)
def get_inventory_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return inventory_service.get(db, company_id, item_id)


@router.patch(
    "/inventory/{item_id}",
    response_model=InventoryItemOut,
    dependencies=[Depends(require_operations)],
)
def update_inventory_item(
    item_id: uuid.UUID,
    body: InventoryItemUpdate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return inventory_service.update(
            db, company_id, item_id, body.model_dump(exclude_unset=True)
        )
