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
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

APP_URL = settings.database_url
SERVICE_URL = settings.service_database_url

# Tables truncated between tests (order-independent with CASCADE).
_TENANT_TABLES = [
    "audit_log", "outbox_events", "public_tokens", "messages", "refunds", "payments",
    "invoices", "estimate_line_items", "estimates", "job_attachments",
    "job_time_entries", "job_line_items", "jobs",
    "inventory_items", "vessels", "customers", "stripe_processed_events",
    "subscriptions", "password_reset_tokens", "user_sessions", "users",
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


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Reset the in-process per-IP rate limiters before each test.

    They are module-level dicts (see `app/core/rate_limit.py`) so state would
    otherwise leak across tests in the same process — the whole suite hits
    `POST /auth/login` etc. from the TestClient's fixed loopback address, so
    without this every test after the ~10th login in a module would see a
    spurious 429 that has nothing to do with what that test is checking.
    """
    from app.core.rate_limit import _reset_all_for_tests

    _reset_all_for_tests()
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


@pytest.fixture
def client() -> Iterator[TestClient]:
    """HTTP client for the real ASGI app (no dependency overrides)."""
    from app.main import app

    with TestClient(app) as c:
        yield c


# Long enough to satisfy PASSWORD_MIN_LENGTH.
DEFAULT_PASSWORD = "correct-horse-battery-staple"


def unique_email(prefix: str = "owner") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def signup(client: TestClient, company_name: str = "Acme Marine",
           email: str | None = None, password: str = DEFAULT_PASSWORD,
           **extra) -> dict:
    """Create a tenant with its first owner; returns the AuthResponse body."""
    body = {
        "company_name": company_name,
        "email": email or unique_email(),
        "password": password,
        **extra,
    }
    resp = client.post("/api/v1/auth/signup", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_headers(auth: dict) -> dict[str, str]:
    """Bearer header from an AuthResponse body (or a bare TokenPair)."""
    tokens = auth.get("tokens", auth)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> dict:
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def invite(client: TestClient, actor: dict, role: str,
           email: str | None = None) -> dict:
    """Provision a user in the actor's tenant and log them in.

    Returns the new user's AuthResponse, with their own id under
    `["user"]["id"]` — which is what the job endpoints want for
    `technician_id`.
    """
    address = email or unique_email(role)
    resp = client.post(
        "/api/v1/auth/users",
        json={"email": address, "password": DEFAULT_PASSWORD, "role": role},
        headers=auth_headers(actor),
    )
    assert resp.status_code == 201, resp.text
    return login(client, address)


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
