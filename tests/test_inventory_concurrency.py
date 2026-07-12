"""Inventory concurrency — the atomic update must not oversell the last unit."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.services.inventory import InsufficientStock, use_inventory_part_atomic
from tests.conftest import make_inventory


def test_atomic_update_deducts_stock(service_db, company_a):
    item = make_inventory(service_db, company_a, "Spark Plug", qty=10)

    eng = create_engine(settings.database_url, future=True)
    Sess = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
    db = Sess()
    try:
        remaining = use_inventory_part_atomic(db, company_a, item, 3)
        assert remaining == 7
    finally:
        db.close()
        eng.dispose()


def test_atomic_update_rejects_negative(service_db, company_a):
    item = make_inventory(service_db, company_a, "Bolt", qty=2)

    eng = create_engine(settings.database_url, future=True)
    Sess = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
    db = Sess()
    try:
        with pytest.raises(InsufficientStock):
            use_inventory_part_atomic(db, company_a, item, 5)
    finally:
        db.close()
        eng.dispose()


def test_concurrent_last_unit_claim_only_one_wins(service_db, company_a):
    """8 threads each try to take the 1 remaining unit — exactly one succeeds."""
    item = make_inventory(service_db, company_a, "Last Gasket", qty=1)

    successes: list[int] = []
    failures: list[int] = []
    lock = threading.Lock()

    def claim():
        eng = create_engine(settings.database_url, future=True)
        Sess = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
        db = Sess()
        try:
            use_inventory_part_atomic(db, company_a, item, 1)
            with lock:
                successes.append(1)
        except InsufficientStock:
            with lock:
                failures.append(1)
        finally:
            db.close()
            eng.dispose()

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _: claim(), range(8)))

    assert len(successes) == 1, f"expected 1 winner, got {len(successes)}"
    assert len(failures) == 7
