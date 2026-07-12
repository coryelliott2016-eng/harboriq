from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class UsePartRequest(BaseModel):
    item_id: str
    quantity: int = Field(gt=0)


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
