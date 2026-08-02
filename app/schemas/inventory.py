import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class UsePartRequest(BaseModel):
    item_id: str
    quantity: int = Field(gt=0)
    #: Bills the part to a work order in the same transaction as the deduction.
    #: Omit it for stock movements that are not against a job.
    job_id: uuid.UUID | None = None


class UsePartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_id: str
    remaining_on_hand: int


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    sku: str | None
    unit_cost: Decimal
    retail_price: Decimal
    quantity_on_hand: int
