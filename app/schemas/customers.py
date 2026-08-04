"""Customer request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.common import OptionalText


class CustomerBase(BaseModel):
    first_name: OptionalText = Field(default=None, max_length=100)
    last_name: OptionalText = Field(default=None, max_length=100)
    #: Set for a business; a private owner has only first/last name.
    company_name: OptionalText = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: OptionalText = Field(default=None, max_length=40)
    address_line1: OptionalText = Field(default=None, max_length=200)
    address_line2: OptionalText = Field(default=None, max_length=200)
    city: OptionalText = Field(default=None, max_length=100)
    state: OptionalText = Field(default=None, max_length=100)
    postal_code: OptionalText = Field(default=None, max_length=20)
    country: OptionalText = Field(default=None, max_length=100)
    notes: OptionalText = None


class CustomerCreate(CustomerBase):
    @model_validator(mode="after")
    def _require_a_name(self) -> CustomerCreate:
        """Mirror the `ck_customers_has_a_name` CHECK so the error is a 422."""
        if not (self.first_name or self.last_name or self.company_name):
            raise ValueError(
                "at least one of first_name, last_name or company_name is required"
            )
        return self


class CustomerUpdate(CustomerBase):
    """Partial update. Only the fields actually present in the body are written.

    The "must still have a name" rule is not re-checked here because validating
    a patch in isolation cannot know the merged result; the DB CHECK is the
    authority and a violation surfaces as a 422.
    """


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    first_name: str | None
    last_name: str | None
    company_name: str | None
    email: str | None
    phone: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    notes: str | None
    # Derived server-side by geocoding address_line1/city/state/postal_code
    # (Phase 10) -- never accepted from the client, always None until a
    # geocode call succeeds. Decimal fields serialize as JSON strings,
    # matching every other Decimal field in this codebase.
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    created_at: datetime
    updated_at: datetime
