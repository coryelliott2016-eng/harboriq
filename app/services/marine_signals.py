"""Curated feed ingestion and tenant-scoped Marine Signals workflows."""
from __future__ import annotations

import email.utils
import html
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.marine_signals import CURATED_SOURCE_HOSTS

logger = logging.getLogger("harboriq.marine_signals")
FRESH_SOURCE_AGE = timedelta(hours=36)
FEED_MAX_BYTES = 2_000_000


def _signal_query(feedback_user_id: uuid.UUID | None = None) -> str:
    feedback_join = ""
    feedback_select = "NULL::text AS feedback, ''::text AS feedback_note"
    if feedback_user_id is not None:
        feedback_select = "f.feedback, COALESCE(f.note, '') AS feedback_note"
        feedback_join = """
            LEFT JOIN marine_signal_feedback f
              ON f.company_id = s.company_id AND f.signal_id = s.id
             AND f.user_id = :user_id
        """
    return f"""
        SELECT s.id, s.source_id, src.name AS source_name, s.category, s.title,
               s.source_content, s.summary, s.why_it_matters, s.suggested_action,
               s.citation_url, s.published_at, s.effective_until, s.geography,
               s.uncertainty, s.priority, s.status, s.reviewed_by, s.reviewed_at,
               s.last_checked_at, s.created_at, {feedback_select}
        FROM marine_signals s
        JOIN marine_signal_sources src
          ON src.company_id = s.company_id AND src.id = s.source_id
        {feedback_join}
        WHERE s.company_id = :company_id
    """


def create_source(db: Session, company_id: uuid.UUID, data: dict) -> dict:
    row = db.execute(
        text(
            """
            INSERT INTO marine_signal_sources (
                company_id, name, category, source_url, feed_url, terms_url,
                terms_reviewed_at
            ) VALUES (
                :company_id, :name, :category, :source_url, :feed_url, :terms_url, now()
            )
            RETURNING id, name, category, source_url, feed_url, terms_url,
                      terms_reviewed_at, enabled, last_checked_at, last_error, created_at
            """
        ),
        {"company_id": company_id, **data},
    ).mappings().one()
    return dict(row)


def list_sources(db: Session, company_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT id, name, category, source_url, feed_url, terms_url,
                   terms_reviewed_at, enabled, last_checked_at, last_error, created_at
            FROM marine_signal_sources
            WHERE company_id = :company_id
            ORDER BY name
            """
        ),
        {"company_id": company_id},
    ).mappings()
    return [dict(row) for row in rows]


def set_source_enabled(
    db: Session, company_id: uuid.UUID, source_id: uuid.UUID, enabled: bool
) -> dict:
    row = db.execute(
        text(
            """
            UPDATE marine_signal_sources
            SET enabled = :enabled, updated_at = now()
            WHERE company_id = :company_id AND id = :source_id
            RETURNING id, name, category, source_url, feed_url, terms_url,
                      terms_reviewed_at, enabled, last_checked_at, last_error, created_at
            """
        ),
        {"company_id": company_id, "source_id": source_id, "enabled": enabled},
    ).mappings().first()
    if row is None:
        raise LookupError("source not found")
    if not enabled:
        db.execute(
            text(
                """
                UPDATE marine_signals
                SET status = 'stale', updated_at = now()
                WHERE company_id = :company_id AND source_id = :source_id
                  AND status = 'published'
                """
            ),
            {"company_id": company_id, "source_id": source_id},
        )
    return dict(row)


def create_signal(db: Session, company_id: uuid.UUID, data: dict) -> dict:
    signal_id = uuid.uuid4()
    row = db.execute(
        text(
            """
            INSERT INTO marine_signals (
                id, company_id, source_id, external_id, category, title,
                source_content, summary, why_it_matters, suggested_action,
                citation_url, published_at, effective_until, geography,
                uncertainty, priority
            )
            SELECT :id, :company_id, src.id, :external_id, :category, :title,
                   :source_content, :summary, :why_it_matters, :suggested_action,
                   :citation_url, :published_at, :effective_until, :geography,
                   :uncertainty, :priority
            FROM marine_signal_sources src
            WHERE src.company_id = :company_id AND src.id = :source_id
            RETURNING id
            """
        ),
        {
            **data,
            "id": signal_id,
            "company_id": company_id,
            "external_id": f"manual:{signal_id}",
        },
    ).first()
    if row is None:
        raise LookupError("source not found")
    return get_signal(db, company_id, signal_id)


def get_signal(
    db: Session, company_id: uuid.UUID, signal_id: uuid.UUID
) -> dict:
    row = db.execute(
        text(_signal_query() + " AND s.id = :signal_id"),
        {"company_id": company_id, "signal_id": signal_id},
    ).mappings().first()
    if row is None:
        raise LookupError("signal not found")
    return dict(row)


def list_signals(
    db: Session,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    include_review: bool,
    category: str | None,
    feedback: str | None,
) -> list[dict]:
    query = _signal_query(user_id)
    params: dict = {"company_id": company_id, "user_id": user_id}
    if not include_review:
        query += " AND s.status = 'published'"
    query += """
        AND (s.status <> 'published' OR s.effective_until IS NULL
             OR s.effective_until > now())
    """
    if category:
        query += " AND s.category = :category"
        params["category"] = category
    if feedback:
        query += " AND f.feedback = :feedback"
        params["feedback"] = feedback
    query += """
        ORDER BY CASE WHEN s.priority = 'urgent' THEN 0 ELSE 1 END,
                 s.published_at DESC NULLS LAST, s.created_at DESC
        LIMIT 250
    """
    rows = db.execute(text(query), params).mappings()
    return [dict(row) for row in rows]


def review_signal(
    db: Session,
    company_id: uuid.UUID,
    signal_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    data: dict,
) -> dict:
    row = db.execute(
        text(
            """
            UPDATE marine_signals
            SET summary = :summary, why_it_matters = :why_it_matters,
                suggested_action = :suggested_action, uncertainty = :uncertainty,
                geography = :geography, priority = :priority, status = 'published',
                reviewed_by = :reviewer_id, reviewed_at = now(), updated_at = now()
            WHERE company_id = :company_id AND id = :signal_id
              AND status = 'needs_review'
              AND citation_url LIKE 'https://%'
            RETURNING id
            """
        ),
        {
            **data,
            "company_id": company_id,
            "signal_id": signal_id,
            "reviewer_id": reviewer_id,
        },
    ).first()
    if row is None:
        raise LookupError("signal not found or no longer needs review")
    return get_signal(db, company_id, signal_id)


def set_signal_status(
    db: Session, company_id: uuid.UUID, signal_id: uuid.UUID, target: str
) -> dict:
    row = db.execute(
        text(
            """
            UPDATE marine_signals
            SET status = :target, updated_at = now()
            WHERE company_id = :company_id AND id = :signal_id
              AND status IN ('published', 'stale')
            RETURNING id
            """
        ),
        {"company_id": company_id, "signal_id": signal_id, "target": target},
    ).first()
    if row is None:
        raise LookupError("published signal not found")
    return get_signal(db, company_id, signal_id)


def add_feedback(
    db: Session,
    company_id: uuid.UUID,
    signal_id: uuid.UUID,
    user_id: uuid.UUID,
    feedback: str,
    note: str,
) -> dict:
    row = db.execute(
        text(
            """
            INSERT INTO marine_signal_feedback (
                company_id, signal_id, user_id, feedback, note
            )
            SELECT :company_id, s.id, :user_id, :feedback, :note
            FROM marine_signals s
            WHERE s.company_id = :company_id AND s.id = :signal_id
              AND s.status = 'published'
            ON CONFLICT (company_id, signal_id, user_id) DO UPDATE
              SET feedback = EXCLUDED.feedback, note = EXCLUDED.note, updated_at = now()
            RETURNING feedback, note, updated_at
            """
        ),
        {
            "company_id": company_id,
            "signal_id": signal_id,
            "user_id": user_id,
            "feedback": feedback,
            "note": note,
        },
    ).mappings().first()
    if row is None:
        raise LookupError("published signal not found")
    return dict(row)


def get_profile(db: Session, company_id: uuid.UUID) -> dict:
    row = db.execute(
        text(
            """
            SELECT service_area, specialties, interests, digest_email,
                   digest_enabled, updated_at
            FROM marine_signal_profiles WHERE company_id = :company_id
            """
        ),
        {"company_id": company_id},
    ).mappings().first()
    return dict(row) if row else {
        "service_area": "",
        "specialties": [],
        "interests": [],
        "digest_email": None,
        "digest_enabled": False,
        "updated_at": None,
    }


def save_profile(db: Session, company_id: uuid.UUID, data: dict) -> dict:
    row = db.execute(
        text(
            """
            INSERT INTO marine_signal_profiles (
                company_id, service_area, specialties, interests,
                digest_email, digest_enabled, updated_at
            ) VALUES (
                :company_id, :service_area, :specialties, :interests,
                :digest_email, :digest_enabled, now()
            )
            ON CONFLICT (company_id) DO UPDATE SET
                service_area = EXCLUDED.service_area,
                specialties = EXCLUDED.specialties,
                interests = EXCLUDED.interests,
                digest_email = EXCLUDED.digest_email,
                digest_enabled = EXCLUDED.digest_enabled,
                updated_at = now()
            RETURNING service_area, specialties, interests, digest_email,
                      digest_enabled, updated_at
            """
        ),
        {"company_id": company_id, **data},
    ).mappings().one()
    return dict(row)


def metrics(db: Session, company_id: uuid.UUID) -> dict:
    row = db.execute(
        text(
            """
            SELECT
              (SELECT count(*) FROM marine_signal_sources
               WHERE company_id = :company_id) AS source_count,
              (SELECT count(*) FROM marine_signal_sources
               WHERE company_id = :company_id AND enabled
                 AND last_checked_at >= now() - interval '36 hours') AS fresh_sources,
              (SELECT count(*) FROM marine_signal_sources
               WHERE company_id = :company_id AND enabled
                 AND (last_checked_at IS NULL OR
                      last_checked_at < now() - interval '36 hours' OR last_error IS NOT NULL))
                AS stale_sources,
              (SELECT count(*) FROM marine_signals
               WHERE company_id = :company_id AND status = 'needs_review') AS needs_review,
              (SELECT count(*) FROM marine_signals
               WHERE company_id = :company_id AND citation_url LIKE 'https://%') AS cited,
              (SELECT count(*) FROM marine_signals WHERE company_id = :company_id) AS total,
              (SELECT count(*) FROM marine_signal_feedback
               WHERE company_id = :company_id AND feedback = 'useful') AS useful_feedback,
              (SELECT count(*) FROM marine_signal_feedback
               WHERE company_id = :company_id AND feedback = 'acted') AS acted_feedback,
              (SELECT count(*) FROM marine_signal_feedback
               WHERE company_id = :company_id) AS feedback_count
            """
        ),
        {"company_id": company_id},
    ).mappings().one()
    values = dict(row)
    values["citation_coverage"] = (
        round(100 * values.pop("cited") / values.pop("total"), 1)
        if values["total"]
        else 0.0
    )
    return values


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)


def _plain_text(value: str, limit: int = 10000) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value[:FEED_MAX_BYTES])
        parsed = " ".join(parser.parts)
    except Exception:  # noqa: BLE001
        parsed = value
    return html.unescape(parsed)[:limit]


def _child_text(element: SafeElementTree.Element, *names: str) -> str:
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names:
            return "".join(child.itertext()).strip()
    return ""


def _entry_url(element: SafeElementTree.Element, feed_url: str) -> str:
    for child in element:
        if child.tag.rsplit("}", 1)[-1].lower() == "link":
            href = child.attrib.get("href") or (child.text or "").strip()
            if href:
                return urljoin(feed_url, href)[:2000]
    return feed_url


def _entry_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_feed(content: bytes, feed_url: str) -> list[dict]:
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("feed may not contain a document type or entity declaration")
    try:
        root = SafeElementTree.fromstring(content, forbid_dtd=True)
    except DefusedXmlException as exc:
        raise ValueError("feed may not contain DTD or entity declarations") from exc
    elements = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}
    ]
    parsed_entries = []
    for entry in elements[:100]:
        title = _child_text(entry, "title")[:250]
        if not title:
            continue
        description = _child_text(
            entry, "description", "summary", "content", "encoded"
        )
        link = _entry_url(entry, feed_url)
        link_host = (urlsplit(link).hostname or "").lower().rstrip(".")
        if link_host not in CURATED_SOURCE_HOSTS:
            link = feed_url
        external_id = (
            _child_text(entry, "guid", "id") or link or title
        )[:2000]
        parsed_entries.append(
            {
                "external_id": external_id,
                "title": title,
                "source_content": _plain_text(description),
                "citation_url": link,
                "published_at": _entry_datetime(
                    _child_text(entry, "pubdate", "published", "updated", "date")
                ),
            }
        )
    return parsed_entries


def refresh_source(db: Session, company_id: uuid.UUID, source_id: uuid.UUID) -> int:
    source = db.execute(
        text(
            """
            SELECT id, name, category, feed_url
            FROM marine_signal_sources
            WHERE company_id = :company_id AND id = :source_id AND enabled
            FOR UPDATE
            """
        ),
        {"company_id": company_id, "source_id": source_id},
    ).mappings().first()
    if source is None:
        return 0
    feed_url = source["feed_url"]
    host = (urlsplit(feed_url).hostname or "").lower().rstrip(".")
    if host not in CURATED_SOURCE_HOSTS:
        raise ValueError("feed URL is not on the curated pilot source allowlist")

    try:
        with httpx.Client(
            timeout=httpx.Timeout(12.0), follow_redirects=False, trust_env=False
        ) as client:
            with client.stream(
                "GET",
                feed_url,
                headers={"User-Agent": "HarborIQ-MarineSignals/1.0 (+https://harboriq.app)"},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                deadline = time.monotonic() + 12
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise TimeoutError("feed download exceeded the 12-second limit")
                    body.extend(chunk)
                    if len(body) > FEED_MAX_BYTES:
                        raise ValueError("feed exceeded the 2 MB size limit")
        entries = _parse_feed(bytes(body), feed_url)
        for entry in entries:
            db.execute(
                text(
                    """
                    INSERT INTO marine_signals (
                        company_id, source_id, external_id, category, title,
                        source_content, citation_url, published_at, last_checked_at
                    ) VALUES (
                        :company_id, :source_id, :external_id, :category, :title,
                        :source_content, :citation_url, :published_at, now()
                    )
                    ON CONFLICT (company_id, source_id, external_id) DO UPDATE SET
                        category = EXCLUDED.category,
                        title = EXCLUDED.title,
                        source_content = EXCLUDED.source_content,
                        citation_url = EXCLUDED.citation_url,
                        published_at = EXCLUDED.published_at,
                        status = CASE
                          WHEN marine_signals.status = 'stale'
                            OR marine_signals.title IS DISTINCT FROM EXCLUDED.title
                            OR marine_signals.source_content
                               IS DISTINCT FROM EXCLUDED.source_content
                            OR marine_signals.citation_url
                               IS DISTINCT FROM EXCLUDED.citation_url
                          THEN 'needs_review'
                          ELSE marine_signals.status
                        END,
                        reviewed_by = CASE
                          WHEN marine_signals.status = 'stale'
                            OR marine_signals.title IS DISTINCT FROM EXCLUDED.title
                            OR marine_signals.source_content
                               IS DISTINCT FROM EXCLUDED.source_content
                            OR marine_signals.citation_url
                               IS DISTINCT FROM EXCLUDED.citation_url
                          THEN NULL ELSE marine_signals.reviewed_by
                        END,
                        reviewed_at = CASE
                          WHEN marine_signals.status = 'stale'
                            OR marine_signals.title IS DISTINCT FROM EXCLUDED.title
                            OR marine_signals.source_content
                               IS DISTINCT FROM EXCLUDED.source_content
                            OR marine_signals.citation_url
                               IS DISTINCT FROM EXCLUDED.citation_url
                          THEN NULL ELSE marine_signals.reviewed_at
                        END,
                        last_checked_at = now(), updated_at = now()
                    """
                ),
                {
                    "company_id": company_id,
                    "source_id": source_id,
                    "category": source["category"],
                    **entry,
                },
            )
        db.execute(
            text(
                """
                UPDATE marine_signals
                SET status = 'stale', updated_at = now()
                WHERE company_id = :company_id AND source_id = :source_id
                  AND status = 'published'
                  AND last_checked_at < now() - interval '21 days'
                """
            ),
            {"company_id": company_id, "source_id": source_id},
        )
        db.execute(
            text(
                """
                UPDATE marine_signal_sources
                SET last_checked_at = now(), last_error = NULL, updated_at = now()
                WHERE company_id = :company_id AND id = :source_id
                """
            ),
            {"company_id": company_id, "source_id": source_id},
        )
        return len(entries)
    except Exception as exc:
        db.execute(
            text(
                """
                UPDATE marine_signal_sources
                SET last_checked_at = now(), last_error = :error, updated_at = now()
                WHERE company_id = :company_id AND id = :source_id
                """
            ),
            {
                "company_id": company_id,
                "source_id": source_id,
                "error": str(exc)[:500],
            },
        )
        logger.warning(
            "marine_signal.source_refresh_failed",
            extra={"source_id": str(source_id), "error": str(exc)[:200]},
        )
        return 0


def expire_signals(db: Session, company_id: uuid.UUID) -> int:
    result = db.execute(
        text(
            """
            UPDATE marine_signals
            SET status = 'stale', updated_at = now()
            WHERE company_id = :company_id AND status = 'published'
              AND effective_until IS NOT NULL AND effective_until <= now()
            """
        ),
        {"company_id": company_id},
    )
    return result.rowcount or 0


def list_digest_signals(db: Session, company_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        text(
            _signal_query()
            + """
              AND s.status = 'published'
              AND COALESCE(s.published_at, s.created_at) >= now() - interval '7 days'
              AND (s.effective_until IS NULL OR s.effective_until > now())
              ORDER BY CASE WHEN s.priority = 'urgent' THEN 0 ELSE 1 END,
                       s.published_at DESC NULLS LAST
              LIMIT 100
            """
        ),
        {"company_id": company_id},
    ).mappings()
    return [dict(row) for row in rows]


def claim_weekly_digest(
    db: Session, company_id: uuid.UUID, week_start
) -> bool:
    claim = db.execute(
        text(
            """
            INSERT INTO marine_signal_digest_deliveries (
                company_id, week_start, status, claimed_at
            ) VALUES (:company_id, :week_start, 'sending', now())
            ON CONFLICT (company_id, week_start) DO UPDATE SET
                status = 'sending', claimed_at = now(), sent_at = NULL
            WHERE marine_signal_digest_deliveries.status <> 'sent'
              AND marine_signal_digest_deliveries.claimed_at < now() - interval '3 hours'
            RETURNING company_id
            """
        ),
        {"company_id": company_id, "week_start": week_start},
    ).first()
    return claim is not None


def finish_weekly_digest(
    db: Session, company_id: uuid.UUID, week_start, *, sent: bool
) -> None:
    if sent:
        db.execute(
            text(
                """
                UPDATE marine_signal_digest_deliveries
                SET status = 'sent', sent_at = now()
                WHERE company_id = :company_id AND week_start = :week_start
                """
            ),
            {"company_id": company_id, "week_start": week_start},
        )
    else:
        db.execute(
            text(
                """
                DELETE FROM marine_signal_digest_deliveries
                WHERE company_id = :company_id AND week_start = :week_start
                  AND status = 'sending'
                """
            ),
            {"company_id": company_id, "week_start": week_start},
        )


def send_digest_email(to: str, week_start, signals: list[dict]) -> bool:
    from app.services import email as email_service
    from app.core.config import settings

    if not settings.smtp_host:
        logger.warning("marine_signal.digest_skipped_no_smtp")
        return False

    lines = [
        "Your HarborIQ Marine Signals weekly digest",
        f"Week beginning {week_start.isoformat()}",
        "",
        "For operational awareness only. Verify safety and regulatory details "
        "with the cited primary source before acting.",
        "",
    ]
    for signal in signals:
        lines.extend(
            [
                f"{'[URGENT] ' if signal['priority'] == 'urgent' else ''}{signal['title']}",
                f"Category: {signal['category']} | Geography: {signal['geography'] or 'Not specified'}",
                signal["summary"],
                f"Why it matters: {signal['why_it_matters']}",
                f"Suggested action: {signal['suggested_action']}",
                f"Uncertainty: {signal['uncertainty'] or 'See source for current details.'}",
                f"Source: {signal['citation_url']}",
                "",
            ]
        )
    return email_service.send_email(
        to=to,
        subject="[HarborIQ] Marine Signals weekly digest",
        text_body="\n".join(lines),
    )
