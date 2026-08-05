"""Recurring/automatic monthly slip storage billing (Phase 17).

`app.services.slip_reservations.generate_recurring_monthly_charge(_for_company)`
is the idempotent, period-scoped counterpart to Phase 15's staff-triggered
`generate_storage_charge`. These tests cover: normal monthly billing,
idempotency (running twice in the same month creates exactly one charge),
correct enumeration of active reservations (statuses/date ranges), and the
Celery Beat task wiring (`app.tasks.sweep_tasks.slip_storage_billing_sweep_task`).
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text

from app.jobs import slip_storage_billing_sweep
from app.services import slip_reservations
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer


def _slip(client, owner, monthly_rate="500.00", **fields):
    body = {
        "identifier": f"A-{uuid.uuid4().hex[:4]}",
        "slip_type": "wet_slip",
        "monthly_rate": monthly_rate,
        **fields,
    }
    resp = client.post("/api/v1/slips", json=body, headers=auth_headers(owner))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _reservation(client, owner, slip_id, customer_id, start, end):
    resp = client.post(
        "/api/v1/slip-reservations",
        json={
            "slip_id": slip_id, "customer_id": customer_id,
            "start_date": start, "end_date": end,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _confirm(client, owner, reservation_id):
    resp = client.post(
        f"/api/v1/slip-reservations/{reservation_id}/confirm",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_generate_recurring_monthly_charge_bills_a_confirmed_reservation(
    client, service_db
):
    owner = signup(client)
    slip_id = _slip(client, owner, monthly_rate="500.00")
    customer_id = make_customer(client, owner)
    rid = uuid.UUID(
        _reservation(client, owner, slip_id, customer_id, "2026-05-01", "2026-08-31")
    )
    _confirm(client, owner, str(rid))

    company_id = uuid.UUID(owner["user"]["company_id"])
    line = slip_reservations.generate_recurring_monthly_charge(
        service_db, company_id, rid, as_of=date(2026, 6, 15)
    )
    assert line is not None
    assert line.kind == "storage"
    assert float(line.unit_price) == 500.0
    assert float(line.quantity) == 1.0
    assert "monthly storage" in line.description


def test_generate_recurring_monthly_charge_is_idempotent_within_the_same_month(
    client, service_db
):
    owner = signup(client)
    slip_id = _slip(client, owner, monthly_rate="500.00")
    customer_id = make_customer(client, owner)
    rid = uuid.UUID(
        _reservation(client, owner, slip_id, customer_id, "2026-05-01", "2026-08-31")
    )
    _confirm(client, owner, str(rid))

    company_id = uuid.UUID(owner["user"]["company_id"])
    first = slip_reservations.generate_recurring_monthly_charge(
        service_db, company_id, rid, as_of=date(2026, 6, 5)
    )
    assert first is not None

    # Second call, same reservation, same calendar month -- must be a no-op,
    # not a second charge (the whole point of idempotency here).
    second = slip_reservations.generate_recurring_monthly_charge(
        service_db, company_id, rid, as_of=date(2026, 6, 28)
    )
    assert second is None

    count = service_db.execute(
        text(
            "SELECT count(*) FROM job_line_items WHERE slip_reservation_id = :id"
        ),
        {"id": rid},
    ).scalar()
    assert count == 1


def test_generate_recurring_monthly_charge_bills_a_new_month_independently(
    client, service_db
):
    owner = signup(client)
    slip_id = _slip(client, owner, monthly_rate="500.00")
    customer_id = make_customer(client, owner)
    rid = uuid.UUID(
        _reservation(client, owner, slip_id, customer_id, "2026-05-01", "2026-08-31")
    )
    _confirm(client, owner, str(rid))

    company_id = uuid.UUID(owner["user"]["company_id"])
    june = slip_reservations.generate_recurring_monthly_charge(
        service_db, company_id, rid, as_of=date(2026, 6, 5)
    )
    july = slip_reservations.generate_recurring_monthly_charge(
        service_db, company_id, rid, as_of=date(2026, 7, 5)
    )
    assert june is not None
    assert july is not None
    assert june.id != july.id

    count = service_db.execute(
        text(
            "SELECT count(*) FROM job_line_items WHERE slip_reservation_id = :id"
        ),
        {"id": rid},
    ).scalar()
    assert count == 2


def test_pending_reservation_is_not_billed(client, service_db):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = uuid.UUID(
        _reservation(client, owner, slip_id, customer_id, "2026-05-01", "2026-08-31")
    )
    # deliberately not confirmed -- still `pending`

    company_id = uuid.UUID(owner["user"]["company_id"])
    line = slip_reservations.generate_recurring_monthly_charge(
        service_db, company_id, rid, as_of=date(2026, 6, 15)
    )
    assert line is None


def test_reservation_outside_the_period_is_not_billed(client, service_db):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = uuid.UUID(
        _reservation(client, owner, slip_id, customer_id, "2026-05-01", "2026-05-10")
    )
    _confirm(client, owner, str(rid))

    company_id = uuid.UUID(owner["user"]["company_id"])
    # This reservation ended in May; billing for July should be a no-op.
    line = slip_reservations.generate_recurring_monthly_charge(
        service_db, company_id, rid, as_of=date(2026, 7, 1)
    )
    assert line is None


def test_generate_recurring_monthly_charges_for_company_enumerates_active_reservations(
    client, service_db
):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    # Active, spans June: billable.
    slip_1 = _slip(client, owner, monthly_rate="400.00")
    rid_1 = uuid.UUID(
        _reservation(client, owner, slip_1, customer_id, "2026-01-01", "2026-12-31")
    )
    _confirm(client, owner, str(rid_1))

    # Cancelled: never billable even though the dates overlap June.
    slip_2 = _slip(client, owner, monthly_rate="400.00")
    rid_2 = uuid.UUID(
        _reservation(client, owner, slip_2, customer_id, "2026-01-01", "2026-12-31")
    )
    cancel_resp = client.post(
        f"/api/v1/slip-reservations/{rid_2}/cancel", headers=auth_headers(owner)
    )
    assert cancel_resp.status_code == 200, cancel_resp.text

    # Short stay in a different month entirely: not billable for June.
    slip_3 = _slip(client, owner, monthly_rate="400.00")
    rid_3 = uuid.UUID(
        _reservation(client, owner, slip_3, customer_id, "2026-09-01", "2026-09-05")
    )
    _confirm(client, owner, str(rid_3))

    result = slip_reservations.generate_recurring_monthly_charges_for_company(
        service_db, company_id, as_of=date(2026, 6, 10)
    )
    assert result["reservations_considered"] == 1
    assert result["charges_created"] == 1

    # Re-running the same period is idempotent: still only one charge total.
    result_again = slip_reservations.generate_recurring_monthly_charges_for_company(
        service_db, company_id, as_of=date(2026, 6, 20)
    )
    assert result_again["reservations_considered"] == 1
    assert result_again["charges_created"] == 0


def test_slip_storage_billing_sweep_job_runs_across_companies(client, service_db):
    owner_a = signup(client)
    customer_a = make_customer(client, owner_a)
    slip_a = _slip(client, owner_a, monthly_rate="300.00")
    rid_a = uuid.UUID(
        _reservation(client, owner_a, slip_a, customer_a, "2026-01-01", "2026-12-31")
    )
    _confirm(client, owner_a, str(rid_a))

    owner_b = signup(client)
    customer_b = make_customer(client, owner_b)
    slip_b = _slip(client, owner_b, monthly_rate="600.00")
    rid_b = uuid.UUID(
        _reservation(client, owner_b, slip_b, customer_b, "2026-01-01", "2026-12-31")
    )
    _confirm(client, owner_b, str(rid_b))

    result = slip_storage_billing_sweep.run(as_of=date(2026, 6, 1))
    assert result["charges_created"] >= 2

    # Idempotent across the whole sweep too.
    result_again = slip_storage_billing_sweep.run(as_of=date(2026, 6, 15))
    assert result_again["charges_created"] == 0


def test_celery_beat_schedule_includes_the_slip_storage_billing_task():
    from app.core.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "slip-storage-billing-daily" in schedule
    assert (
        schedule["slip-storage-billing-daily"]["task"]
        == "app.tasks.sweep_tasks.slip_storage_billing_sweep_task"
    )


def test_celery_beat_schedule_includes_dunning_sweep():
    """A. 1 -- confirm the dunning sweep beat entry (shipped by the
    concurrently-committing process this phase; asserted here so this
    phase's test suite documents/locks in that it is indeed scheduled, not
    just callable on demand)."""
    from app.core.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "dunning-sweep-hourly" in schedule
    assert (
        schedule["dunning-sweep-hourly"]["task"]
        == "app.tasks.sweep_tasks.dunning_sweep_task"
    )


def test_slip_storage_billing_sweep_task_calls_through(monkeypatch):
    from app.tasks import sweep_tasks

    calls = []
    monkeypatch.setattr(
        sweep_tasks.slip_storage_billing_sweep,
        "run",
        lambda: calls.append(1)
        or {"company_count": 1, "reservations_considered": 2, "charges_created": 2},
    )
    result = sweep_tasks.slip_storage_billing_sweep_task.delay()
    assert result.get() == {
        "company_count": 1,
        "reservations_considered": 2,
        "charges_created": 2,
    }
    assert len(calls) == 1
