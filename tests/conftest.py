"""Shared pytest fixtures.

Requires a live PostgreSQL with the HarborIQ schema migrated. Tests run against
the app role (RLS-enforced) and the service role (BYPASSRLS).

Because RLS and concurrency tests span MULTIPLE database sessions, setup data
must be COMMITTED to be visible across sessions. An autouse fixture truncates
all tenant tables between tests for isolation.

Run with:
    docker compose up -d db
    alembic upgrade head
    pytest
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

APP_URL = settings.database_url
SERVICE_URL = settings.service_database_url

# Tables truncated between tests (order-independent with CASCADE).
_TENANT_TABLES = [
    "audit_log", "outbox_events", "public_tokens", "payments", "invoices",
    "estimate_line_items", "estimates", "jobs", "inventory_items", "vessels",
    "customers", "stripe_processed_events", "subscriptions", "users",
    "subscription_plans", "companies",
]


@pytest.fixture(scope="session")
def app_engine():
    eng = create_engine(APP_URL, future=True, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def service_engine():
    eng = create_engine(SERVICE_URL, future=True, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _truncate(service_engine):
    """Truncate tenant data before each test (committed)."""
    eng = create_engine(SERVICE_URL, future=True)
    with eng.begin() as conn:
        for t in _TENANT_TABLES:
            conn.execute(text(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE"))
    eng.dispose()
    yield


@pytest.fixture
def app_db(app_engine) -> Iterator[Session]:
    maker = sessionmaker(bind=app_engine, class_=Session, expire_on_commit=False)
    db = maker()
    yield db
    db.close()


@pytest.fixture
def service_db(service_engine) -> Iterator[Session]:
    maker = sessionmaker(bind=service_engine, class_=Session, expire_on_commit=False)
    db = maker()
    yield db
    db.close()


def _create_company(db: Session, slug: str) -> uuid.UUID:
    row = db.execute(
        text("INSERT INTO companies (slug, name) VALUES (:slug, :name) RETURNING id"),
        {"slug": slug, "name": slug.replace("-", " ").title()},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


@pytest.fixture
def company_a(service_db) -> uuid.UUID:
    return _create_company(service_db, f"acme-marine-{uuid.uuid4().hex[:6]}")


@pytest.fixture
def company_b(service_db) -> uuid.UUID:
    return _create_company(service_db, f"bayside-yachts-{uuid.uuid4().hex[:6]}")


def make_inventory(db: Session, company_id: uuid.UUID, name: str, qty: int,
                   unit_cost: str = "12.99", retail: str = "29.99") -> uuid.UUID:
    row = db.execute(
        text(
            """
            INSERT INTO inventory_items
                (company_id, name, sku, unit_cost, retail_price, quantity_on_hand)
            VALUES (:cid, :name, :sku, :uc, :rp, :qty)
            RETURNING id
            """
        ),
        {"cid": company_id, "name": name, "sku": name.upper(),
         "uc": unit_cost, "rp": retail, "qty": qty},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


def make_estimate(db: Session, company_id: uuid.UUID, status: str = "sent",
                  total: str = "100.00") -> uuid.UUID:
    row = db.execute(
        text(
            """
            INSERT INTO estimates (company_id, status, total, balance_due)
            VALUES (:cid, :status, :total, :total)
            RETURNING id
            """
        ),
        {"cid": company_id, "status": status, "total": total},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))
