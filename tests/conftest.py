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
    "crypto_processed_events", "crypto_payments",
    "token_ledger_entries", "asset_tokens",
    "invoices", "estimate_line_items", "estimates", "job_attachments",
    "job_time_entries", "dry_stack_launch_requests", "job_line_items",
    "slip_reservations", "slips", "jobs",
    "purchase_order_line_items", "purchase_orders", "vendors",
    "inventory_items", "vessels", "customers", "stripe_processed_events",
    "subscriptions", "password_reset_tokens", "mfa_backup_codes",
    "user_sessions", "users",
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
    """Reset the Redis-backed per-IP rate limiters before each test.

    Counters live in Redis, keyed by IP (see `app/core/rate_limit.py`), so
    state would otherwise leak across tests in the same process — the whole
    suite hits `POST /auth/login` etc. from the TestClient's fixed loopback
    address, so without this every test after the ~10th login in a module
    would see a spurious 429 that has nothing to do with what that test is
    checking.
    """
    from app.core.rate_limit import _reset_all_for_tests

    _reset_all_for_tests()
    yield


@pytest.fixture(autouse=True, scope="session")
def _celery_eager_mode():
    """Run Celery tasks synchronously/in-process for the whole test session.

    `dispatch_outbox_soon` (see `app/services/outbox_dispatch.py`) enqueues a
    real Celery task via `.delay()`. Flipping `task_always_eager` on here
    means that call executes the task body immediately, in the calling
    thread, with no broker or worker process required — the standard Celery
    testing pattern. This preserves the exact behavior tests already depend
    on from the pre-Phase-16 BackgroundTasks version: the dispatch pass has
    already run by the time `client.post(...)` returns.
    """
    from app.core.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
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
                   unit_cost: str = "12.99", retail: str = "29.99",
                   reorder_point: int = 0, sku: str | None = None) -> uuid.UUID:
    # Historically this always derived `sku` from `name.upper()`; Phase 13's
    # `uq_inventory_items_company_sku` partial unique index means two calls
    # with the same `name` in the same test/company would now collide, so
    # callers that need multiple items sharing a name (rare) can pass an
    # explicit `sku=None` override, or a distinct one.
    row = db.execute(
        text(
            """
            INSERT INTO inventory_items
                (company_id, name, sku, unit_cost, retail_price, quantity_on_hand,
                 reorder_point)
            VALUES (:cid, :name, :sku, :uc, :rp, :qty, :reorder_point)
            RETURNING id
            """
        ),
        {"cid": company_id, "name": name, "sku": sku if sku is not None else name.upper(),
         "uc": unit_cost, "rp": retail, "qty": qty, "reorder_point": reorder_point},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


def make_vendor(db: Session, company_id: uuid.UUID, name: str = "Acme Marine Supply",
                contact_email: str | None = "orders@acmemarine.test") -> uuid.UUID:
    row = db.execute(
        text(
            """
            INSERT INTO vendors (company_id, name, contact_email)
            VALUES (:cid, :name, :email)
            RETURNING id
            """
        ),
        {"cid": company_id, "name": name, "email": contact_email},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


def make_purchase_order(
    db: Session,
    company_id: uuid.UUID,
    vendor_id: uuid.UUID,
    created_by: uuid.UUID,
    line_items: list[tuple[uuid.UUID, int, str]],
    status: str = "draft",
) -> uuid.UUID:
    """`line_items` is `[(inventory_item_id, quantity_ordered, unit_cost), ...]`."""
    po_row = db.execute(
        text(
            """
            INSERT INTO purchase_orders (company_id, vendor_id, created_by, status)
            VALUES (:cid, :vendor_id, :created_by, CAST(:status AS purchase_order_status))
            RETURNING id
            """
        ),
        {"cid": company_id, "vendor_id": vendor_id, "created_by": created_by, "status": status},
    ).first()
    po_id = uuid.UUID(str(po_row[0]))
    for item_id, qty, unit_cost in line_items:
        db.execute(
            text(
                """
                INSERT INTO purchase_order_line_items
                    (company_id, purchase_order_id, inventory_item_id, quantity_ordered, unit_cost)
                VALUES (:cid, :po_id, :item_id, :qty, :unit_cost)
                """
            ),
            {"cid": company_id, "po_id": po_id, "item_id": item_id, "qty": qty, "unit_cost": unit_cost},
        )
    db.commit()
    return po_id


def make_slip(
    db: Session,
    company_id: uuid.UUID,
    identifier: str = "A-1",
    slip_type: str = "wet_slip",
    status: str = "available",
    daily_rate: str = "25.00",
    monthly_rate: str = "400.00",
) -> uuid.UUID:
    row = db.execute(
        text(
            """
            INSERT INTO slips
                (company_id, identifier, slip_type, status, daily_rate, monthly_rate)
            VALUES
                (:cid, :identifier, CAST(:slip_type AS slip_type),
                 CAST(:status AS slip_status), :daily_rate, :monthly_rate)
            RETURNING id
            """
        ),
        {
            "cid": company_id,
            "identifier": identifier,
            "slip_type": slip_type,
            "status": status,
            "daily_rate": daily_rate,
            "monthly_rate": monthly_rate,
        },
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
