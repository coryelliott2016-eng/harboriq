"""PDF invoice generation + email delivery (Phase 8).

Three layers, matching the module split (`invoice_pdf` is DB-agnostic,
`invoice_render` is the DB glue, `outbox`/`email` are the delivery path):

1. `render_invoice_pdf` against hand-built dataclasses -- no DB needed.
2. `build_invoice_pdf_bytes` against a real invoice created through the API.
3. End-to-end: `outbox.dispatch_pending` sends an email with the PDF
   attached, verified via the console-transport monkeypatch convention
   already used in `tests/test_email_and_outbox_dispatch.py`.

No real network calls anywhere (no Stripe, no real SMTP).
"""
from __future__ import annotations

import io
import uuid
from decimal import Decimal

from pypdf import PdfReader
from sqlalchemy import text

from app.services import email, outbox
from app.services.invoice_pdf import InvoicePdfData, InvoicePdfLineItem, render_invoice_pdf
from app.services.invoice_render import build_invoice_pdf_bytes
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ---------------------------------------------------------------------------
# 1. render_invoice_pdf (DB-agnostic)
# ---------------------------------------------------------------------------
def test_render_invoice_pdf_contains_key_fields():
    invoice_id = uuid.uuid4()
    data = InvoicePdfData(
        invoice_id=invoice_id,
        company_name="Off the Hook Marine",
        status="sent",
        subtotal=Decimal("250.00"),
        tax_total=Decimal("17.50"),
        total=Decimal("267.50"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("267.50"),
        currency="USD",
        customer_name="Jane Boatowner",
        customer_email="jane@example.com",
        vessel_name="Second Wind",
        pay_url="https://pay.example.com/abc123",
        line_items=[
            InvoicePdfLineItem(
                description="Outboard tune-up",
                quantity=Decimal("1.00"),
                unit_price=Decimal("150.00"),
                line_total=Decimal("150.00"),
            ),
            InvoicePdfLineItem(
                description="Impeller replacement",
                quantity=Decimal("2.00"),
                unit_price=Decimal("50.00"),
                line_total=Decimal("100.00"),
            ),
        ],
    )

    pdf_bytes = render_invoice_pdf(data)
    assert pdf_bytes[:4] == b"%PDF"

    text_content = _pdf_text(pdf_bytes)
    assert "Off the Hook Marine" in text_content
    assert str(invoice_id) in text_content
    assert "Jane Boatowner" in text_content
    assert "Second Wind" in text_content
    assert "Outboard tune-up" in text_content
    assert "Impeller replacement" in text_content
    assert "267.50" in text_content
    assert "https://pay.example.com/abc123" in text_content


def test_render_invoice_pdf_handles_missing_optional_fields():
    """No customer, no vessel, no pay_url, no line items -- must still
    render rather than raising (e.g. a draft invoice with a job that has no
    vessel on file)."""
    data = InvoicePdfData(
        invoice_id=uuid.uuid4(),
        company_name="Off the Hook Marine",
        status="draft",
        subtotal=Decimal("0.00"),
        tax_total=Decimal("0.00"),
        total=Decimal("0.00"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("0.00"),
        currency="USD",
        customer_name=None,
        customer_email=None,
        vessel_name=None,
        pay_url=None,
        line_items=[],
    )
    pdf_bytes = render_invoice_pdf(data)
    assert pdf_bytes[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 2. build_invoice_pdf_bytes (DB glue)
# ---------------------------------------------------------------------------
def _invoiced_job(client, actor, unit_price="125.00"):
    customer_id = make_customer(client, actor, last_name="Halyard")
    job = make_job(client, actor, customer_id).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={
            "kind": "labor",
            "description": "Engine diagnostic",
            "quantity": "1.00",
            "unit_price": unit_price,
        },
        headers=auth_headers(actor),
    )
    resp = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(actor)
    )
    assert resp.status_code == 201, resp.text
    return job, resp.json(), customer_id


def test_build_invoice_pdf_bytes_renders_a_real_invoice(client, service_db):
    owner = signup(client, company_name="Off the Hook Marine")
    _job_id, invoice, customer_id = _invoiced_job(client, owner)
    service_db.execute(
        text("UPDATE customers SET email = 'jane@example.com' WHERE id = :id"),
        {"id": customer_id},
    )
    service_db.commit()

    pdf_bytes = build_invoice_pdf_bytes(service_db, uuid.UUID(invoice["id"]))
    assert pdf_bytes is not None
    assert pdf_bytes[:4] == b"%PDF"

    text_content = _pdf_text(pdf_bytes)
    assert "Off the Hook Marine" in text_content
    assert invoice["id"] in text_content
    assert "125.00" in text_content
    assert "Engine diagnostic" in text_content


def test_build_invoice_pdf_bytes_returns_none_for_an_unknown_invoice(service_db):
    assert build_invoice_pdf_bytes(service_db, uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# 3. End-to-end: outbox dispatch attaches the PDF to the sent email
# ---------------------------------------------------------------------------
def test_sending_an_invoice_dispatches_an_email_with_the_pdf_attached(
    client, service_db, monkeypatch
):
    owner = signup(client, company_name="Off the Hook Marine")
    _job_id, invoice, customer_id = _invoiced_job(client, owner)
    service_db.execute(
        text("UPDATE customers SET email = 'customer@example.com' WHERE id = :id"),
        {"id": customer_id},
    )
    service_db.commit()

    sent = []
    monkeypatch.setattr(
        email,
        "send_email",
        lambda to, subject, body, html_body=None, attachments=None: (
            sent.append((to, subject, body, attachments)) or True
        ),
    )

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text

    # `send` schedules a FastAPI BackgroundTask (`dispatch_outbox_soon`);
    # TestClient runs background tasks synchronously right after the
    # response is returned, so the row is already dispatched by now -- no
    # second `dispatch_pending` call is needed (or correct: the row would
    # already be gone, making a second call here always return 0).
    assert len(sent) == 1
    to, subject, body, attachments = sent[0]
    assert to == "customer@example.com"
    assert "invoice" in subject.lower()

    assert attachments is not None and len(attachments) == 1
    filename, pdf_bytes, mime_subtype = attachments[0]
    assert filename == "invoice.pdf"
    assert mime_subtype == "pdf"
    assert pdf_bytes[:4] == b"%PDF"
    assert invoice["id"] in _pdf_text(pdf_bytes)


def test_dispatch_degrades_gracefully_when_invoice_cannot_be_resolved(
    monkeypatch, app_db, service_db, company_a
):
    """Covers the same graceful-degradation contract as the existing
    `test_email_and_outbox_dispatch.py` assertion, from this file's more
    PDF-focused angle: a payload whose invoice_id does not resolve to a real
    row must still deliver the email, just without a PDF attached."""
    from app.db.tenant import tenant_context

    sent = []
    monkeypatch.setattr(
        email,
        "send_email",
        lambda to, subject, body, html_body=None, attachments=None: (
            sent.append(attachments) or True
        ),
    )

    with tenant_context(app_db, company_a):
        outbox.enqueue(
            app_db,
            company_a,
            "invoice.send",
            {
                "invoice_id": str(uuid.uuid4()),
                "customer_email": "someone@example.com",
                "pay_url": "/api/v1/public/invoice/tok",
            },
        )
        app_db.commit()

    dispatched = outbox.dispatch_pending(service_db)
    assert dispatched == 1
    assert sent[0] in (None, [])
