"""Vendor request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import OptionalText, RequiredText


class VendorBase(BaseModel):
    name: RequiredText = Field(max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: OptionalText = Field(default=None, max_length=40)
    notes: OptionalText = None


class VendorCreate(VendorBase):
    pass


class VendorUpdate(BaseModel):
    name: RequiredText | None = Field(default=None, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: OptionalText = Field(default=None, max_length=40)
    notes: OptionalText = None


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    contact_email: str | None
    contact_phone: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VendorStatusUpdate(BaseModel):
    """Body for POST /vendors/{vendor_id}/status -- deactivate (archive) or
    reactivate a vendor. Deliberately its own endpoint/schema rather than a
    field on `VendorUpdate`: a lifecycle change is a distinct action from an
    ordinary contact-info edit (same reasoning as job status transitions).
    """

    is_active: bool
