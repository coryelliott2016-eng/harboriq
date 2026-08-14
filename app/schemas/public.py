import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.schemas.invoices import InvoiceLineItemOut


class ApproveEstimateRequest(BaseModel):
    estimate_pdf_version: str = "1"


class ApproveEstimateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    company_id: str
    estimate_id: str
    status: str = "approved"


class PublicInvoiceOut(BaseModel):
    """What an unauthenticated customer sees on the pay page.

    Deliberately narrower than `InvoiceOut` — no `company_id`, no internal
    Stripe checkout-session id beyond the redirect URL a fresh session needs.
    """

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    # datetime, not str: populated straight from the ORM row via
    # `from_attributes` (Invoice.due_date is a tz-aware DateTime column);
    # pydantic serializes it to an ISO-8601 string in the JSON response.
    due_date: datetime | None = None
    line_items: list[InvoiceLineItemOut] = []
    #: Present only when Stripe is configured and the invoice is still
    #: payable (not already paid/void); lazily created on first read.
    checkout_url: str | None = None
