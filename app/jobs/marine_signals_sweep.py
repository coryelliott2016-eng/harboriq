"""Refresh approved Marine Signals feeds and send opt-in weekly digests."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.db.session import AppSession, ServiceSession
from app.db.tenant import set_tenant
from app.services import marine_signals

logger = logging.getLogger("harboriq.marine_signals.sweep")


def refresh_all_sources() -> dict[str, int]:
    service_db = ServiceSession()
    try:
        targets = service_db.execute(
            text(
                "SELECT company_id, id FROM marine_signal_sources WHERE enabled ORDER BY company_id"
            )
        ).all()
    finally:
        service_db.close()

    result = {"sources_checked": 0, "signals_seen": 0, "errors": 0, "expired": 0}
    for company_id, source_id in targets:
        db = AppSession()
        try:
            set_tenant(db, company_id)
            result["signals_seen"] += marine_signals.refresh_source(
                db, company_id, source_id
            )
            result["expired"] += marine_signals.expire_signals(db, company_id)
            db.commit()
            result["sources_checked"] += 1
        except Exception:  # noqa: BLE001
            db.rollback()
            result["errors"] += 1
            logger.exception(
                "marine_signals.refresh_task_failed",
                extra={"company_id": str(company_id), "source_id": str(source_id)},
            )
        finally:
            db.close()
    return result


def send_weekly_digests(now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    this_monday = now.date() - timedelta(days=now.weekday())
    week_start = this_monday - timedelta(days=7)
    service_db = ServiceSession()
    try:
        profiles = service_db.execute(
            text(
                """
                SELECT company_id, digest_email, interests
                FROM marine_signal_profiles
                WHERE digest_enabled AND digest_email IS NOT NULL
                """
            )
        ).mappings().all()
    finally:
        service_db.close()

    result = {"recipients": 0, "sent": 0, "skipped": 0, "failed": 0}
    for profile in profiles:
        company_id = profile["company_id"]
        db = AppSession()
        try:
            set_tenant(db, company_id)
            signals = marine_signals.list_digest_signals(db, company_id)
            interests = set(profile["interests"] or [])
            if interests:
                signals = [item for item in signals if item["category"] in interests]
            if not signals:
                db.rollback()
                result["skipped"] += 1
                continue
            if not marine_signals.claim_weekly_digest(db, company_id, week_start):
                db.rollback()
                result["skipped"] += 1
                continue
            db.commit()
            result["recipients"] += 1
            sent = marine_signals.send_digest_email(
                profile["digest_email"], week_start, signals
            )
            set_tenant(db, company_id)
            marine_signals.finish_weekly_digest(
                db, company_id, week_start, sent=sent
            )
            db.commit()
            result["sent" if sent else "failed"] += 1
        except Exception:  # noqa: BLE001
            db.rollback()
            result["failed"] += 1
            logger.exception(
                "marine_signals.digest_delivery_failed",
                extra={"company_id": str(company_id)},
            )
        finally:
            db.close()
    return result


if __name__ == "__main__":
    print(refresh_all_sources())
    if date.today().weekday() == 0:
        print(send_weekly_digests())
