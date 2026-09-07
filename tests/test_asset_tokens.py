"""Phase 19 — draft-only asset-tokenization registration coverage."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer


def _enable_asset_tokenization(monkeypatch) -> None:
    monkeypatch.setattr(settings, "asset_tokenization_enabled", True)


def _make_vessel(client, actor) -> dict:
    customer = make_customer(client, actor)
    response = client.post(
        "/api/v1/vessels",
        json={
            "customer_id": customer,
            "name": "Tokenization Test Vessel",
            "hull_id": f"HIN-{uuid.uuid4().hex[:12]}",
        },
        headers=auth_headers(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _register_vessel_token(client, actor, vessel_id: str) -> dict:
    response = client.post(
        "/api/v1/asset-tokens",
        json={
            "asset_type": "vessel",
            "vessel_id": vessel_id,
            "source_description": "2024 harbor workboat retained for exploratory review",
            "estimated_value": "250000.00",
            "notes": "Draft record only; no securities activity.",
        },
        headers=auth_headers(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_feature_flag_off_returns_not_found(client, monkeypatch):
    owner = signup(client)
    monkeypatch.setattr(settings, "asset_tokenization_enabled", False)

    response = client.post(
        "/api/v1/asset-tokens",
        json={
            "asset_type": "equipment",
            "source_description": "Travel lift identified for preliminary review",
        },
        headers=auth_headers(owner),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "asset tokenization is not enabled"


def test_operations_user_is_forbidden_on_every_asset_token_endpoint(client, monkeypatch):
    _enable_asset_tokenization(monkeypatch)
    owner = signup(client)
    office = invite(client, owner, "office")
    asset_token_id = uuid.uuid4()

    create = client.post(
        "/api/v1/asset-tokens",
        json={
            "asset_type": "equipment",
            "source_description": "Travel lift identified for preliminary review",
        },
        headers=auth_headers(office),
    )
    listed = client.get("/api/v1/asset-tokens", headers=auth_headers(office))
    fetched = client.get(
        f"/api/v1/asset-tokens/{asset_token_id}",
        headers=auth_headers(office),
    )

    assert create.status_code == 403
    assert listed.status_code == 403
    assert fetched.status_code == 403


def test_admin_registers_draft_vessel_token_with_one_registered_ledger_entry(
    client, monkeypatch, service_db
):
    _enable_asset_tokenization(monkeypatch)
    owner = signup(client)
    vessel = _make_vessel(client, owner)

    registered = _register_vessel_token(client, owner, vessel["id"])
    asset_token = registered["asset_token"]
    ledger_entry = registered["ledger_entry"]

    assert asset_token["status"] == "draft"
    assert asset_token["asset_type"] == "vessel"
    assert asset_token["vessel_id"] == vessel["id"]
    assert ledger_entry["asset_token_id"] == asset_token["id"]
    assert ledger_entry["entry_type"] == "registered"

    ledger_rows = service_db.execute(
        text(
            """
            SELECT entry_type
              FROM token_ledger_entries
             WHERE asset_token_id = :asset_token_id
            """
        ),
        {"asset_token_id": asset_token["id"]},
    ).all()
    assert [row.entry_type for row in ledger_rows] == ["registered"]

    listed = client.get("/api/v1/asset-tokens", headers=auth_headers(owner))
    fetched = client.get(
        f"/api/v1/asset-tokens/{asset_token['id']}",
        headers=auth_headers(owner),
    )
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [asset_token["id"]]
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == asset_token["id"]


def test_vessel_asset_requires_a_vessel_id(client, monkeypatch):
    _enable_asset_tokenization(monkeypatch)
    owner = signup(client)

    response = client.post(
        "/api/v1/asset-tokens",
        json={
            "asset_type": "vessel",
            "source_description": "Vessel record awaiting identification",
        },
        headers=auth_headers(owner),
    )

    assert response.status_code == 422
    assert "vessel_id is required" in response.json()["detail"]


def test_vessel_asset_rejects_a_cross_tenant_vessel(client, monkeypatch):
    _enable_asset_tokenization(monkeypatch)
    owner_a = signup(client, company_name="Asset Token Tenant A")
    vessel_a = _make_vessel(client, owner_a)
    owner_b = signup(client, company_name="Asset Token Tenant B")

    response = client.post(
        "/api/v1/asset-tokens",
        json={
            "asset_type": "vessel",
            "vessel_id": vessel_a["id"],
            "source_description": "Foreign tenant vessel must not be referenceable",
        },
        headers=auth_headers(owner_b),
    )

    assert response.status_code == 404
    assert "vessel" in response.json()["detail"]


def test_asset_token_is_not_visible_to_another_tenant(client, monkeypatch):
    _enable_asset_tokenization(monkeypatch)
    owner_a = signup(client, company_name="Asset Token Tenant A")
    vessel_a = _make_vessel(client, owner_a)
    registered = _register_vessel_token(client, owner_a, vessel_a["id"])
    owner_b = signup(client, company_name="Asset Token Tenant B")

    response = client.get(
        f"/api/v1/asset-tokens/{registered['asset_token']['id']}",
        headers=auth_headers(owner_b),
    )

    assert response.status_code == 404


def test_no_asset_token_mutation_routes_are_registered(client, monkeypatch):
    _enable_asset_tokenization(monkeypatch)
    owner = signup(client)
    asset_token_id = uuid.uuid4()
    path = f"/api/v1/asset-tokens/{asset_token_id}"

    responses = [
        client.patch(path, json={"status": "issued"}, headers=auth_headers(owner)),
        client.put(path, json={"status": "issued"}, headers=auth_headers(owner)),
        client.delete(path, headers=auth_headers(owner)),
    ]

    assert all(response.status_code in {404, 405} for response in responses)


def test_database_status_check_rejects_any_non_draft_value(client, monkeypatch, service_db):
    _enable_asset_tokenization(monkeypatch)
    owner = signup(client)
    vessel = _make_vessel(client, owner)
    registered = _register_vessel_token(client, owner, vessel["id"])
    asset_token_id = registered["asset_token"]["id"]

    definition = service_db.execute(
        text(
            """
            SELECT pg_get_constraintdef(oid)
              FROM pg_constraint
             WHERE conrelid = 'asset_tokens'::regclass
               AND conname = 'ck_asset_tokens_status_draft'
            """
        )
    ).scalar_one()
    assert "status = 'draft'" in definition

    with pytest.raises(IntegrityError):
        service_db.execute(
            text("UPDATE asset_tokens SET status = 'issued' WHERE id = :id"),
            {"id": asset_token_id},
        )
        service_db.commit()
    service_db.rollback()

    status_value = service_db.execute(
        text("SELECT status FROM asset_tokens WHERE id = :id"),
        {"id": asset_token_id},
    ).scalar_one()
    assert status_value == "draft"
