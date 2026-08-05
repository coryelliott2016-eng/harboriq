"""Slip double-booking is prevented at the DATABASE level, not just by the
advisory application-side check.

`app.services.slip_reservations.create` does check availability before
inserting, but that check and the insert are not atomic across sessions --
two concurrent callers can both pass the check before either commits. The
real guarantee is `ex_slip_reservations_no_overlap`, the `btree_gist`
EXCLUDE constraint on `slip_reservations(slip_id, stay_range)` added by
migration 0016. This test fires genuinely concurrent create attempts (each
on its own connection/session, like `test_inventory_concurrency.py` does for
`use_inventory_part_atomic`) for the exact same slip and overlapping dates,
and asserts exactly one wins.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.services import slip_reservations as service
from app.services.crud import Conflict
from tests.conftest import make_slip


def _make_customer_db(db, company_id, last_name="Halyard"):
    from sqlalchemy import text

    row = db.execute(
        text("INSERT INTO customers (company_id, last_name) VALUES (:cid, :name) RETURNING id"),
        {"cid": company_id, "name": last_name},
    ).first()
    db.commit()
    return row[0]


def test_concurrent_overlapping_reservations_only_one_wins(service_db, company_a):
    slip_id = make_slip(service_db, company_a, identifier="CONC-1")
    customer_id = _make_customer_db(service_db, company_a)

    start = date(2026, 7, 1)
    end = date(2026, 7, 10)

    successes: list[object] = []
    failures: list[Exception] = []
    lock = threading.Lock()

    def attempt():
        eng = create_engine(settings.database_url, future=True)
        Sess = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
        db = Sess()
        try:
            row = service.create(db, company_a, slip_id, customer_id, start, end)
            with lock:
                successes.append(row)
        except Conflict as exc:
            with lock:
                failures.append(exc)
        finally:
            db.close()
            eng.dispose()

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _: attempt(), range(8)))

    assert len(successes) == 1, f"expected exactly 1 winner, got {len(successes)}"
    assert len(failures) == 7, f"expected exactly 7 rejected, got {len(failures)}"


def test_concurrent_partially_overlapping_reservations_only_one_wins(service_db, company_a):
    """Same idea, but each thread requests a *different* (still-overlapping)
    range on the same slip, proving the EXCLUDE constraint compares ranges
    with `&&` (overlap), not row equality."""
    slip_id = make_slip(service_db, company_a, identifier="CONC-2")
    customer_id = _make_customer_db(service_db, company_a)

    ranges = [
        (date(2026, 8, 1), date(2026, 8, 10)),
        (date(2026, 8, 5), date(2026, 8, 15)),
        (date(2026, 8, 8), date(2026, 8, 20)),
        (date(2026, 8, 9), date(2026, 8, 9)),
        (date(2026, 8, 3), date(2026, 8, 25)),
        (date(2026, 8, 1), date(2026, 8, 30)),
    ]

    successes: list[object] = []
    failures: list[Exception] = []
    lock = threading.Lock()

    def attempt(bounds):
        s, e = bounds
        eng = create_engine(settings.database_url, future=True)
        Sess = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
        db = Sess()
        try:
            row = service.create(db, company_a, slip_id, customer_id, s, e)
            with lock:
                successes.append(row)
        except Conflict as exc:
            with lock:
                failures.append(exc)
        finally:
            db.close()
            eng.dispose()

    with ThreadPoolExecutor(max_workers=len(ranges)) as ex:
        list(ex.map(attempt, ranges))

    assert len(successes) == 1, f"expected exactly 1 winner, got {len(successes)}"
    assert len(failures) == len(ranges) - 1


def test_non_overlapping_concurrent_reservations_on_same_slip_all_succeed(service_db, company_a):
    """Sanity check the constraint isn't overly broad: genuinely disjoint
    date ranges on the same slip must all be allowed to book concurrently."""
    slip_id = make_slip(service_db, company_a, identifier="CONC-3")
    customer_id = _make_customer_db(service_db, company_a)

    ranges = [
        (date(2026, 9, 1), date(2026, 9, 5)),
        (date(2026, 9, 6), date(2026, 9, 10)),
        (date(2026, 9, 11), date(2026, 9, 15)),
        (date(2026, 9, 16), date(2026, 9, 20)),
    ]

    successes: list[object] = []
    failures: list[Exception] = []
    lock = threading.Lock()

    def attempt(bounds):
        s, e = bounds
        eng = create_engine(settings.database_url, future=True)
        Sess = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
        db = Sess()
        try:
            row = service.create(db, company_a, slip_id, customer_id, s, e)
            with lock:
                successes.append(row)
        except Conflict as exc:
            with lock:
                failures.append(exc)
        finally:
            db.close()
            eng.dispose()

    with ThreadPoolExecutor(max_workers=len(ranges)) as ex:
        list(ex.map(attempt, ranges))

    assert len(failures) == 0, f"unexpected rejections on disjoint ranges: {failures}"
    assert len(successes) == len(ranges)
