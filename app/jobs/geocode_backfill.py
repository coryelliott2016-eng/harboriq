"""Geocoding backfill — `python -m app.jobs.geocode_backfill`.

Phases 6-9 created seed/test data (customers with addresses, users with no
address field at all until this phase) with no coordinates populated —
migration 0006 added `latitude`/`longitude` columns but nothing ever filled
them in. This job closes that gap for existing rows.

Same "no Celery/Redis task queue yet" posture as `dunning_sweep.py`: a plain
script an external scheduler can invoke, iterating every company via the
SERVICE session (BYPASSRLS). Also reachable per-tenant, on demand, via
`POST /admin/geocode-backfill` (`app/api/v1/routes/geocode_admin.py`) for an
admin who does not want to wait for a scheduled run.

Idempotent by construction: only rows with an address AND null coordinates
are selected, unless `force=True` re-geocodes everything with an address
regardless of existing coordinates. Running it twice without `force` is a
no-op the second time.

Tenant-isolated: every UPDATE is scoped to `company_id = :cid` in its WHERE
clause (this runs on the SERVICE/BYPASSRLS session precisely because it must
cross tenants to backfill the whole platform in one pass, so the query
itself — not RLS — is what keeps one company's backfill from touching
another's rows).

Companies are deliberately NOT backfilled here: `companies` has no free-text
address column (see migration 0009's SQL comment) so there is nothing to
geocode FROM. A company that already has hand-set `latitude`/`longitude`
needs no backfill; one that doesn't has no address this job could derive
coordinates from.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import ServiceSession
from app.services import geocoding

logger = logging.getLogger("harboriq.jobs.geocode_backfill")


def _customer_address(row) -> str | None:
    parts = [row.address_line1, row.city, row.state, row.postal_code]
    joined = ", ".join(p for p in parts if p and p.strip())
    return joined or None


def backfill_customers(db: Session, company_id: uuid.UUID, *, force: bool = False) -> int:
    """Geocode customers with an address and (by default) null coordinates.

    Returns the number of rows updated (coordinates actually populated —
    a row whose address fails to geocode is attempted but not counted,
    matching the "did this backfill make progress" intent of the return
    value).
    """
    where_coords = "" if force else "AND latitude IS NULL"
    rows = db.execute(
        text(
            f"""
            SELECT id, address_line1, city, state, postal_code
              FROM customers
             WHERE company_id = :cid
               AND address_line1 IS NOT NULL
               AND BTRIM(address_line1) <> ''
               {where_coords}
            """
        ),
        {"cid": company_id},
    ).all()

    updated = 0
    for row in rows:
        address = _customer_address(row)
        if not address:
            continue
        result = geocoding.geocode(address)
        if result is None:
            continue
        lat, lon = result
        db.execute(
            text(
                "UPDATE customers SET latitude = :lat, longitude = :lon, "
                "updated_at = now() WHERE id = :id AND company_id = :cid"
            ),
            {"lat": lat, "lon": lon, "id": row.id, "cid": company_id},
        )
        updated += 1
    db.commit()
    return updated


def backfill_users(db: Session, company_id: uuid.UUID, *, force: bool = False) -> int:
    """Geocode users (technicians) with an `address_text` and (by default)
    null home coordinates."""
    where_coords = "" if force else "AND home_latitude IS NULL"
    rows = db.execute(
        text(
            f"""
            SELECT id, address_text
              FROM users
             WHERE company_id = :cid
               AND address_text IS NOT NULL
               AND BTRIM(address_text) <> ''
               {where_coords}
            """
        ),
        {"cid": company_id},
    ).all()

    updated = 0
    for row in rows:
        result = geocoding.geocode(row.address_text)
        if result is None:
            continue
        lat, lon = result
        # users has no updated_at column (see app/db/models.py).
        db.execute(
            text(
                "UPDATE users SET home_latitude = :lat, home_longitude = :lon "
                "WHERE id = :id AND company_id = :cid"
            ),
            {"lat": lat, "lon": lon, "id": row.id, "cid": company_id},
        )
        updated += 1
    db.commit()
    return updated


def backfill_company(db: Session, company_id: uuid.UUID, *, force: bool = False) -> dict[str, int]:
    """Backfill both customers and users for one tenant. Used by both the
    on-demand admin route and the all-tenants script below."""
    return {
        "customers_updated": backfill_customers(db, company_id, force=force),
        "users_updated": backfill_users(db, company_id, force=force),
    }


def run(*, force: bool = False) -> dict[str, int]:
    """Run the backfill for every company. Returns aggregate counts."""
    db = ServiceSession()
    try:
        company_ids = [row.id for row in db.execute(text("SELECT id FROM companies"))]

        totals = {"company_count": len(company_ids), "customers_updated": 0, "users_updated": 0}
        for company_id in company_ids:
            result = backfill_company(db, company_id, force=force)
            totals["customers_updated"] += result["customers_updated"]
            totals["users_updated"] += result["users_updated"]
            if result["customers_updated"] or result["users_updated"]:
                logger.info(
                    "geocode backfill: company=%s customers=%d users=%d",
                    company_id,
                    result["customers_updated"],
                    result["users_updated"],
                )

        logger.info(
            "geocode backfill complete: companies=%d customers=%d users=%d",
            totals["company_count"],
            totals["customers_updated"],
            totals["users_updated"],
        )
        return totals
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    run(force="--force" in sys.argv)
