"""Tenant isolation still holds once the tenant comes from a verified token."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.db.tenant import tenant_context
from tests.conftest import (
    DEFAULT_PASSWORD,
    auth_headers,
    make_inventory,
    signup,
    unique_email,
)


def test_users_are_invisible_across_tenants_under_rls(client, app_db):
    a = signup(client, company_name="Acme Marine")
    b = signup(client, company_name="Bayside Yachts")

    with tenant_context(app_db, a["user"]["company_id"]):
        visible = app_db.execute(text("SELECT id::text FROM users")).scalars().all()
    assert visible == [a["user"]["id"]]
    assert b["user"]["id"] not in visible


def test_sessions_are_invisible_across_tenants_under_rls(client, app_db):
    a = signup(client)
    b = signup(client)

    with tenant_context(app_db, a["user"]["company_id"]):
        owners = app_db.execute(
            text("SELECT DISTINCT user_id::text FROM user_sessions")
        ).scalars().all()
    assert owners == [a["user"]["id"]]
    assert b["user"]["id"] not in owners


def test_companies_are_isolated_under_rls(client, app_db):
    a = signup(client)
    signup(client)

    with tenant_context(app_db, a["user"]["company_id"]):
        rows = app_db.execute(text("SELECT id::text FROM companies")).scalars().all()
    assert rows == [a["user"]["company_id"]]


def test_no_tenant_context_means_no_rows(client, app_db):
    signup(client)
    assert app_db.execute(text("SELECT count(*) FROM users")).scalar_one() == 0
    assert app_db.execute(text("SELECT count(*) FROM user_sessions")).scalar_one() == 0


def test_inventory_endpoint_is_scoped_to_the_token_tenant(client, service_db):
    """Tenant A's token cannot touch tenant B's stock, even knowing its item id."""
    a = signup(client, company_name="Acme Marine")
    b = signup(client, company_name="Bayside Yachts")
    b_item = make_inventory(service_db, uuid.UUID(b["user"]["company_id"]), "impeller", 10)

    resp = client.post(
        "/api/v1/inventory/use",
        json={"item_id": str(b_item), "quantity": 1},
        headers=auth_headers(a),
    )
    # Indistinguishable from out-of-stock: the row is simply not visible.
    assert resp.status_code == 409

    remaining = service_db.execute(
        text("SELECT quantity_on_hand FROM inventory_items WHERE id = :iid"),
        {"iid": b_item},
    ).scalar_one()
    assert remaining == 10

    ok = client.post(
        "/api/v1/inventory/use",
        json={"item_id": str(b_item), "quantity": 1},
        headers=auth_headers(b),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["remaining_on_hand"] == 9


def test_a_spoofed_company_id_header_is_ignored(client, service_db):
    """The legacy X-Company-Id header must no longer grant anything."""
    a = signup(client, company_name="Acme Marine")
    b = signup(client, company_name="Bayside Yachts")
    b_item = make_inventory(service_db, uuid.UUID(b["user"]["company_id"]), "anode", 5)

    resp = client.post(
        "/api/v1/inventory/use",
        json={"item_id": str(b_item), "quantity": 1},
        headers={**auth_headers(a), "X-Company-Id": b["user"]["company_id"]},
    )
    assert resp.status_code == 409

    assert service_db.execute(
        text("SELECT quantity_on_hand FROM inventory_items WHERE id = :iid"),
        {"iid": b_item},
    ).scalar_one() == 5


def test_inventory_endpoint_requires_authentication(client, service_db, company_a):
    item = make_inventory(service_db, company_a, "prop", 3)
    resp = client.post(
        "/api/v1/inventory/use", json={"item_id": str(item), "quantity": 1}
    )
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_a_token_for_a_deleted_company_is_rejected(client, service_db):
    created = signup(client)
    service_db.execute(
        text("DELETE FROM user_sessions WHERE company_id = :cid"),
        {"cid": created["user"]["company_id"]},
    )
    service_db.execute(
        text("DELETE FROM users WHERE company_id = :cid"),
        {"cid": created["user"]["company_id"]},
    )
    service_db.commit()

    assert client.get("/api/v1/auth/me", headers=auth_headers(created)).status_code == 401


def test_the_same_email_can_be_reused_after_the_account_is_removed(client, service_db):
    email = unique_email()
    created = signup(client, email=email)
    service_db.execute(
        text("DELETE FROM user_sessions WHERE user_id = :uid"),
        {"uid": created["user"]["id"]},
    )
    service_db.execute(
        text("DELETE FROM users WHERE id = :uid"), {"uid": created["user"]["id"]}
    )
    service_db.commit()

    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Second Chance Marine",
            "email": email,
            "password": DEFAULT_PASSWORD,
        },
    )
    assert resp.status_code == 201
