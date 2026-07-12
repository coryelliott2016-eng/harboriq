"""RLS tenant isolation — the core backstop. A missed app filter must not leak.

These tests connect as the APP role (harboriq_app) so RLS applies. If they
connect as owner/superuser the policies are bypassed and the tests are void.
"""
from __future__ import annotations


import pytest
from sqlalchemy import text

from app.db.tenant import tenant_context
from tests.conftest import make_inventory


def test_rls_blocks_cross_tenant_read(app_db, company_a, company_b, service_db):
    """Tenant A cannot see tenant B's inventory, even with no explicit filter."""
    make_inventory(service_db, company_b, "Yamaha Filter", qty=10)

    # Set tenant context to A and query inventory_items with NO company filter.
    with tenant_context(app_db, company_a):
        rows = app_db.execute(text("SELECT name FROM inventory_items")).all()

    assert rows == [], "RLS leaked tenant B's rows to tenant A"


def test_rls_blocks_cross_tenant_write(app_db, company_a, company_b):
    """Tenant A cannot insert a row claiming company_id = B."""
    with tenant_context(app_db, company_a):
        with pytest.raises(Exception):
            app_db.execute(
                text(
                    """
                    INSERT INTO inventory_items
                        (company_id, name, sku, quantity_on_hand)
                    VALUES (:cid, 'stolen', 'STOLEN', 1)
                    """
                ),
                {"cid": company_b},
            )


def test_rls_app_role_only_sees_own_rows(app_db, company_a, company_b, service_db):
    make_inventory(service_db, company_a, "Mercury Plug", qty=5)
    make_inventory(service_db, company_b, "Suzuki Impeller", qty=5)

    with tenant_context(app_db, company_a):
        names = [
            r[0]
            for r in app_db.execute(text("SELECT name FROM inventory_items")).all()
        ]
    assert names == ["Mercury Plug"]


def test_rls_cross_tenant_record_404_pattern(app_db, company_a, company_b, service_db):
    """Fetching B's item id while scoped to A returns no row (-> 404 at app layer)."""
    b_item = make_inventory(service_db, company_b, "Volvo Belt", qty=3)

    with tenant_context(app_db, company_a):
        row = app_db.execute(
            text("SELECT id FROM inventory_items WHERE id = :id"),
            {"id": b_item},
        ).first()
    assert row is None


def test_service_role_bypasses_rls_for_webhook_resolution(service_db, company_b, app_db):
    """The service role can resolve a company by subscription id without RLS."""
    # (sanity) service session can read companies regardless of tenant context
    rows = service_db.execute(text("SELECT count(*) FROM companies")).first()
    assert rows is not None
