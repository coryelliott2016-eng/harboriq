"""Audit trail coverage for money and privilege events (v0.2.1).

`audit_log` existed since migration 0001 and already recorded auth events and
estimate send/convert. These tests pin the v0.2.1 additions:

* invoice send / void / refund write `invoice.*` rows in the same transaction;
* admin role and activation changes write `user.*` rows, and a no-op PATCH
  that re-sends the current role does not;
* `GET /api/v1/audit-log` is owner/admin only, newest-first, keyset-paginated,
  filterable by action prefix, and — because the table is RLS-scoped — can
  never show another tenant's rows.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import auth_headers, invite, signup
from tests.test_invoicing_lifecycle import _invoiced_job
from tests.test_refunds import _mock_refund, _pay


def _entries(client, actor, **params):
    resp = client.get("/api/v1/audit-log", params=params, headers=auth_headers(actor))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _actions(page) -> list[str]:
    return [item["action"] for item in page["items"]]


# ---------------------------------------------------------------------------
# Invoice lifecycle events
# ---------------------------------------------------------------------------

def test_sending_an_invoice_records_an_audit_row_with_the_actor(client):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)

    resp = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text

    page = _entries(client, owner, action="invoice.sent")
    assert len(page["items"]) == 1
    row = page["items"][0]
    assert row["resource_type"] == "invoice"
    assert row["resource_id"] == invoice["id"]
    assert row["actor_user_id"] == owner["user"]["id"]
    assert row["actor_email"] == owner["user"]["email"]
    assert row["metadata"]["total"] == invoice["total"]
    assert row["metadata"]["stripe_checkout"] is False  # no Stripe key in tests


def test_voiding_an_invoice_records_previous_status(client):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)

    resp = client.post(f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text

    page = _entries(client, owner, action="invoice.voided")
    assert len(page["items"]) == 1
    assert page["items"][0]["metadata"]["previous_status"] == "draft"
    assert page["items"][0]["resource_id"] == invoice["id"]


def test_a_rejected_void_leaves_no_audit_row(client, service_db):
    """The audit row must commit *with* the transition, never on its own."""
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    # Simulate collected money so the void is refused with 409.
    service_db.execute(
        text("UPDATE invoices SET amount_paid = total, status = 'paid' WHERE id = :id"),
        {"id": invoice["id"]},
    )
    service_db.commit()

    resp = client.post(f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(owner))
    assert resp.status_code == 409, resp.text
    assert _entries(client, owner, action="invoice.voided")["items"] == []


def test_refunding_an_invoice_records_amount_and_reason(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="80.00")
    _pay(client, service_db, owner, invoice, cents=8000)
    _mock_refund(monkeypatch, refund_id="re_test_audit")

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund",
        json={"amount": "30.00", "reason": "goodwill"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text

    page = _entries(client, owner, action="invoice.refunded")
    assert len(page["items"]) == 1
    meta = page["items"][0]["metadata"]
    assert meta["amount"] == "30.00"
    assert meta["reason"] == "goodwill"
    assert meta["stripe_refund_id"] == "re_test_audit"
    assert meta["new_status"] == "partially_refunded"
    assert page["items"][0]["actor_user_id"] == owner["user"]["id"]


# ---------------------------------------------------------------------------
# Privilege changes
# ---------------------------------------------------------------------------

def test_role_change_and_deactivation_are_audited_but_noop_patch_is_not(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    tech_id = tech["user"]["id"]

    # The invite itself is audited by the auth service (user.invited, user.login).
    # Those are not under test here; only the privilege-change actions are.
    privilege_actions = {"user.role_changed", "user.deactivated", "user.reactivated"}

    def privilege_rows():
        page = _entries(client, owner, action="user.", resource_id=tech_id)
        return [item for item in page["items"] if item["action"] in privilege_actions]

    # No-op: re-sending the current role must not create a row.
    resp = client.patch(
        f"/api/v1/users/{tech_id}", json={"role": "technician"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert _entries(client, owner, action="user.role_changed", resource_id=tech_id)["items"] == []

    resp = client.patch(
        f"/api/v1/users/{tech_id}", json={"role": "office"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    resp = client.patch(
        f"/api/v1/users/{tech_id}", json={"is_active": False}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text

    rows = privilege_rows()
    assert [r["action"] for r in rows] == ["user.deactivated", "user.role_changed"]  # newest first
    role_row = rows[1]
    assert role_row["metadata"] == {
        "from": "technician", "to": "office", "email": tech["user"]["email"],
    }
    assert role_row["resource_id"] == tech_id
    assert role_row["actor_user_id"] == owner["user"]["id"]


# ---------------------------------------------------------------------------
# Read endpoint: authorization, isolation, pagination
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["technician", "office"])
def test_non_admins_cannot_read_the_audit_log(client, role):
    owner = signup(client)
    member = invite(client, owner, role)
    resp = client.get("/api/v1/audit-log", headers=auth_headers(member))
    assert resp.status_code == 403, resp.text


def test_admin_can_read_the_audit_log(client):
    owner = signup(client)
    admin = invite(client, owner, "admin")
    resp = client.get("/api/v1/audit-log", headers=auth_headers(admin))
    assert resp.status_code == 200, resp.text


def test_audit_log_is_tenant_scoped(client):
    owner_a = signup(client, company_name="Tenant A")
    owner_b = signup(client, company_name="Tenant B")
    _job_id, invoice_a = _invoiced_job(client, owner_a)
    client.post(f"/api/v1/invoices/{invoice_a['id']}/void", headers=auth_headers(owner_a))

    assert "invoice.voided" in _actions(_entries(client, owner_a, action="invoice."))
    page_b = _entries(client, owner_b)
    assert all(item["resource_id"] != invoice_a["id"] for item in page_b["items"])
    assert "invoice.voided" not in _actions(page_b)
    # Explicit filter by the other tenant's resource id must also come back empty.
    assert _entries(client, owner_b, resource_id=invoice_a["id"])["items"] == []


def test_audit_log_pages_newest_first_with_keyset_cursor(client):
    owner = signup(client)
    for _ in range(3):
        _job_id, invoice = _invoiced_job(client, owner)
        client.post(f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(owner))

    first = _entries(client, owner, action="invoice.voided", limit=2)
    assert len(first["items"]) == 2
    assert first["next_before_id"] == first["items"][-1]["id"]
    assert first["items"][0]["id"] > first["items"][1]["id"]

    second = _entries(
        client, owner, action="invoice.voided", limit=2, before_id=first["next_before_id"]
    )
    assert len(second["items"]) == 1
    assert second["next_before_id"] is None
    assert second["items"][0]["id"] < first["items"][-1]["id"]


def test_audit_log_rejects_oversized_pages(client):
    owner = signup(client)
    resp = client.get("/api/v1/audit-log", params={"limit": 1000}, headers=auth_headers(owner))
    assert resp.status_code == 422
