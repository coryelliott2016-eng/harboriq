"""Tests for `app/jobs/geocode_backfill.py` and `POST /admin/geocode-backfill`.

Covers: only null-coordinate rows are touched by default, tenant isolation,
idempotency (a second run without `force` is a no-op), and the `force`
flag re-geocoding everything with an address regardless of existing
coordinates. Nominatim is mocked throughout -- no real network calls.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import text

from app.jobs import geocode_backfill
from tests.conftest import auth_headers, invite, signup


def _make_customer_with_address(client, actor, address_line1="100 Main St", city="Sarasota"):
    resp = client.post(
        "/api/v1/customers",
        json={"last_name": "Halyard", "address_line1": address_line1, "city": city, "state": "FL"},
        headers=auth_headers(actor),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _clear_coords(service_db, table, row_id):
    service_db.execute(text(f"UPDATE {table} SET latitude = NULL, longitude = NULL WHERE id = :id"), {"id": row_id})
    service_db.commit()


def _clear_user_coords(service_db, user_id):
    service_db.execute(
        text("UPDATE users SET home_latitude = NULL, home_longitude = NULL WHERE id = :id"),
        {"id": user_id},
    )
    service_db.commit()


def _fake_geocode(_address):
    return (Decimal("27.3364"), Decimal("-82.5307"))


def test_backfill_customers_geocodes_only_addressed_null_coordinate_rows(client, service_db):
    owner = signup(client)
    with patch("app.services.geocoding.geocode", return_value=None):
        customer_id = _make_customer_with_address(client, owner)
    # create() already tried to geocode above (mocked to None) -- confirm
    # coordinates are null before backfill, as a real "un-geocoded seed
    # data" row would be.
    row = service_db.execute(
        text("SELECT latitude, longitude FROM customers WHERE id = :id"), {"id": customer_id}
    ).one()
    assert row.latitude is None

    company_id = owner["user"]["company_id"]
    with patch("app.services.geocoding.geocode", side_effect=_fake_geocode):
        updated = geocode_backfill.backfill_customers(service_db, company_id)

    assert updated == 1
    row = service_db.execute(
        text("SELECT latitude, longitude FROM customers WHERE id = :id"), {"id": customer_id}
    ).one()
    assert row.latitude == Decimal("27.3364")
    assert row.longitude == Decimal("-82.5307")


def test_backfill_customers_skips_rows_that_already_have_coordinates(client, service_db):
    owner = signup(client)
    with patch("app.services.geocoding.geocode", side_effect=_fake_geocode):
        _make_customer_with_address(client, owner)

    company_id = owner["user"]["company_id"]
    with patch("app.services.geocoding.geocode") as mocked:
        updated = geocode_backfill.backfill_customers(service_db, company_id)

    assert updated == 0
    mocked.assert_not_called()


def test_backfill_customers_skips_rows_with_no_address(client, service_db):
    owner = signup(client)
    resp = client.post(
        "/api/v1/customers", json={"last_name": "NoAddress"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 201, resp.text

    company_id = owner["user"]["company_id"]
    with patch("app.services.geocoding.geocode") as mocked:
        updated = geocode_backfill.backfill_customers(service_db, company_id)

    assert updated == 0
    mocked.assert_not_called()


def test_backfill_customers_force_reGeocodes_even_with_existing_coordinates(client, service_db):
    owner = signup(client)
    with patch("app.services.geocoding.geocode", side_effect=_fake_geocode):
        customer_id = _make_customer_with_address(client, owner)

    company_id = owner["user"]["company_id"]
    new_coords = (Decimal("10.0"), Decimal("20.0"))
    with patch("app.services.geocoding.geocode", side_effect=lambda _a: new_coords):
        updated = geocode_backfill.backfill_customers(service_db, company_id, force=True)

    assert updated == 1
    row = service_db.execute(
        text("SELECT latitude, longitude FROM customers WHERE id = :id"), {"id": customer_id}
    ).one()
    assert row.latitude == Decimal("10.0")
    assert row.longitude == Decimal("20.0")


def test_backfill_users_geocodes_addressed_null_coordinate_technicians(client, service_db):
    owner = signup(client)
    with patch("app.services.geocoding.geocode", return_value=None):
        tech = invite(client, owner, "technician")
        client.patch(
            f"/api/v1/users/{tech['user']['id']}",
            json={"address_text": "500 Dock Rd, Bradenton, FL"},
            headers=auth_headers(tech),
        )

    company_id = owner["user"]["company_id"]
    with patch("app.services.geocoding.geocode", side_effect=_fake_geocode):
        updated = geocode_backfill.backfill_users(service_db, company_id)

    assert updated == 1
    row = service_db.execute(
        text("SELECT home_latitude, home_longitude FROM users WHERE id = :id"),
        {"id": tech["user"]["id"]},
    ).one()
    assert row.home_latitude == Decimal("27.3364")


def test_backfill_is_tenant_isolated(client, service_db):
    owner_a = signup(client)
    with patch("app.services.geocoding.geocode", return_value=None):
        customer_a = _make_customer_with_address(client, owner_a)

    owner_b = signup(client)
    with patch("app.services.geocoding.geocode", side_effect=_fake_geocode):
        updated = geocode_backfill.backfill_customers(
            service_db, owner_b["user"]["company_id"]
        )

    assert updated == 0
    row = service_db.execute(
        text("SELECT latitude FROM customers WHERE id = :id"), {"id": customer_a}
    ).one()
    assert row.latitude is None


def test_running_backfill_twice_without_force_is_idempotent(client, service_db):
    owner = signup(client)
    with patch("app.services.geocoding.geocode", return_value=None):
        _make_customer_with_address(client, owner)

    company_id = owner["user"]["company_id"]
    with patch("app.services.geocoding.geocode", side_effect=_fake_geocode) as mocked:
        first_run = geocode_backfill.backfill_customers(service_db, company_id)
        second_run = geocode_backfill.backfill_customers(service_db, company_id)

    assert first_run == 1
    assert second_run == 0
    assert mocked.call_count == 1


def test_admin_backfill_route_requires_admin(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.post("/api/v1/admin/geocode-backfill", headers=auth_headers(tech))
    assert resp.status_code == 403, resp.text


def test_admin_backfill_route_runs_for_the_callers_company(client, service_db):
    owner = signup(client)
    with patch("app.services.geocoding.geocode", return_value=None):
        _make_customer_with_address(client, owner)

    with patch("app.services.geocoding.geocode", side_effect=_fake_geocode):
        resp = client.post(
            "/api/v1/admin/geocode-backfill", headers=auth_headers(owner)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["customers_updated"] == 1
    assert body["users_updated"] == 0
