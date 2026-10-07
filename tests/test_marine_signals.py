"""Marine Signals source validation and feed parsing tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.db.tenant import set_tenant
from app.jobs import marine_signals_sweep as sweep
from app.schemas.marine_signals import MarineSignalCreate, MarineSignalReview, MarineSignalSourceCreate
from app.services import marine_signals
from app.services.marine_signals import _parse_feed
from app.services.outbox import _build_email
from tests.conftest import auth_headers, invite, signup


def _create_source(client, actor):
    response = client.post(
        "/api/v1/marine-signals/sources",
        json={
            "name": "NWS Tampa Bay",
            "category": "weather",
            "source_url": "https://www.weather.gov/tbw/",
            "feed_url": "https://www.weather.gov/tbw/rss.xml",
            "terms_url": "https://www.weather.gov/disclaimer",
            "terms_confirmed": True,
        },
        headers=auth_headers(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_signal(client, actor, source_id, title, published_at=None):
    body = {
        "source_id": source_id,
        "category": "weather",
        "title": title,
        "citation_url": "https://www.weather.gov/tbw/outlook",
    }
    if published_at is not None:
        body["published_at"] = published_at.isoformat()
    response = client.post(
        "/api/v1/marine-signals/signals", json=body, headers=auth_headers(actor)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _review_signal(client, actor, signal_id, *, priority="normal"):
    response = client.post(
        f"/api/v1/marine-signals/signals/{signal_id}/review",
        json={
            "summary": "Verified forecast update.",
            "why_it_matters": "Work planning may be affected.",
            "suggested_action": "Check the source before scheduling.",
            "uncertainty": "Forecast details may change.",
            "geography": "Florida Gulf Coast",
            "priority": priority,
        },
        headers=auth_headers(actor),
    )
    return response


@pytest.mark.no_db
def test_source_requires_terms_confirmation_and_same_approved_host():
    valid = {
        "name": "NWS Tampa Bay",
        "category": "weather",
        "source_url": "https://www.weather.gov/tbw/",
        "feed_url": "https://www.weather.gov/tbw/rss.xml",
        "terms_url": "https://www.weather.gov/disclaimer",
        "terms_confirmed": True,
    }
    source = MarineSignalSourceCreate.model_validate(valid)
    assert str(source.feed_url) == valid["feed_url"]

    with pytest.raises(ValidationError):
        MarineSignalSourceCreate.model_validate({**valid, "terms_confirmed": False})
    with pytest.raises(ValidationError):
        MarineSignalSourceCreate.model_validate(
            {**valid, "feed_url": "https://feeds.example.net/weather.xml"}
        )
    with pytest.raises(ValidationError):
        MarineSignalSourceCreate.model_validate(
            {**valid, "source_url": "http://www.weather.gov/tbw/"}
        )
    with pytest.raises(ValidationError):
        MarineSignalSourceCreate.model_validate(
            {**valid, "feed_url": "https://www.weather.gov:8443/tbw/rss.xml"}
        )
    with pytest.raises(ValidationError):
        MarineSignalSourceCreate.model_validate(
            {**valid, "feed_url": "https://www.weather.gov/tbw/rss.xml?token=secret"}
        )


@pytest.mark.no_db
def test_rss_parser_extracts_citation_and_plain_text():
    xml = b"""<?xml version="1.0"?>
    <rss><channel><item>
      <guid>storm-42</guid>
      <title>Gulf marine outlook</title>
      <link>https://www.weather.gov/tbw/outlook</link>
      <description><![CDATA[<p>Rough <b>conditions</b> possible.</p>]]></description>
      <pubDate>Mon, 05 Oct 2026 12:00:00 GMT</pubDate>
    </item></channel></rss>"""
    entry = _parse_feed(xml, "https://www.weather.gov/tbw/feed.xml")[0]
    assert entry["external_id"] == "storm-42"
    assert entry["citation_url"] == "https://www.weather.gov/tbw/outlook"
    assert entry["source_content"] == "Rough conditions possible."
    assert entry["published_at"].isoformat() == "2026-10-05T12:00:00+00:00"


@pytest.mark.no_db
def test_rss_parser_falls_back_from_unapproved_item_link_and_rejects_entities():
    xml = b"""<rss><channel><item>
      <title>Notice</title><link>https://attacker.example/item</link>
      <description>Details</description>
    </item></channel></rss>"""
    entry = _parse_feed(xml, "https://www.weather.gov/tbw/feed.xml")[0]
    assert entry["citation_url"] == "https://www.weather.gov/tbw/feed.xml"
    no_link_ids = _parse_feed(
        b"<rss><channel><item><title>First notice</title></item>"
        b"<item><title>Second notice</title></item></channel></rss>",
        "https://www.weather.gov/tbw/feed.xml",
    )
    assert [entry["external_id"] for entry in no_link_ids] == [
        "First notice",
        "Second notice",
    ]
    relative_link = b"<feed><entry><title>Update</title><link href='/alerts/1'/></entry></feed>"
    relative_entry = _parse_feed(
        relative_link, "https://www.weather.gov/tbw/feed.xml"
    )[0]
    assert relative_entry["citation_url"] == "https://www.weather.gov/alerts/1"

    with pytest.raises(ValueError, match="entity"):
        _parse_feed(
            b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss><channel></channel></rss>',
            "https://www.weather.gov/tbw/feed.xml",
        )


@pytest.mark.no_db
def test_urgent_alert_email_keeps_citation_and_verification_caveat():
    email = _build_email(
        None,
        "marine_signal.urgent_alert",
        {
            "to": "shop@example.com",
            "title": "Rough Gulf conditions",
            "summary": "Conditions may deteriorate late week.",
            "why_it_matters": "Outdoor work may be interrupted.",
            "suggested_action": "Protect unfinished boats.",
            "uncertainty": "Forecast may change.",
            "citation_url": "https://www.weather.gov/tbw/outlook",
        },
    )
    assert email is not None
    assert email[0] == "shop@example.com"
    assert email[1].startswith("[HarborIQ] Urgent")
    assert "https://www.weather.gov/tbw/outlook" in email[2]
    assert "Verify safety and regulatory details" in email[2]


@pytest.mark.no_db
def test_review_requires_nonblank_context_and_signal_dates_are_aware():
    with pytest.raises(ValidationError):
        MarineSignalReview(
            summary=" ",
            why_it_matters="Impact",
            suggested_action="Action",
            geography="Florida",
            uncertainty="Forecast may change.",
        )
    review = MarineSignalReview(
        summary="Summary",
        why_it_matters="Impact",
        suggested_action="Action",
        geography=" Florida ",
        uncertainty=" Forecast may change. ",
    )
    assert review.geography == "Florida"
    assert review.uncertainty == "Forecast may change."
    for field in ("geography", "uncertainty"):
        review_data = {
            "summary": "Summary",
            "why_it_matters": "Impact",
            "suggested_action": "Action",
            "geography": "Florida",
            "uncertainty": "Forecast may change.",
        }
        review_data[field] = "   "
        with pytest.raises(ValidationError):
            MarineSignalReview(**review_data)
    with pytest.raises(ValidationError):
        MarineSignalReview(
            summary="Summary",
            why_it_matters="Impact",
            suggested_action="Action",
        )

    with pytest.raises(ValidationError):
        MarineSignalCreate(
            source_id="9d95aa92-28fc-4436-b457-d6d9f6e81157",
            category="weather",
            title="Outlook",
            citation_url="https://www.weather.gov/tbw/outlook",
            published_at="2026-10-05T12:00:00",
        )


def test_marine_signals_review_is_role_and_tenant_scoped_and_enqueues_alert(
    client, service_db
):
    owner = signup(client, company_name="Marine Signals A")
    other_tenant = signup(client, company_name="Marine Signals B")
    company_id = uuid.UUID(owner["user"]["company_id"])
    source = _create_source(client, owner)
    normal_signal = _create_signal(client, owner, source["id"], "Weather update")
    urgent_signal = _create_signal(client, owner, source["id"], "Urgent weather update")

    profile_response = client.put(
        "/api/v1/marine-signals/profile",
        json={
            "service_area": "Alaska",
            "interests": ["fuel"],
            "digest_email": "alerts@example.com",
            "digest_enabled": True,
        },
        headers=auth_headers(owner),
    )
    assert profile_response.status_code == 200, profile_response.text

    office = invite(client, owner, "office")
    pending = client.get(
        "/api/v1/marine-signals/signals?include_review=true",
        headers=auth_headers(office),
    )
    assert pending.status_code == 200, pending.text
    assert {signal["id"] for signal in pending.json()} == {
        normal_signal["id"],
        urgent_signal["id"],
    }
    assert client.put(
        "/api/v1/marine-signals/profile",
        json={"service_area": "Florida"},
        headers=auth_headers(office),
    ).status_code == 403
    assert _review_signal(client, office, normal_signal["id"]).status_code == 403

    reviewed = _review_signal(client, owner, normal_signal["id"])
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "published"
    published_filtered = client.get(
        "/api/v1/marine-signals/signals", headers=auth_headers(office)
    )
    assert published_filtered.status_code == 200, published_filtered.text
    assert normal_signal["id"] not in {
        signal["id"] for signal in published_filtered.json()
    }

    urgent_review = _review_signal(
        client, owner, urgent_signal["id"], priority="urgent"
    )
    assert urgent_review.status_code == 200, urgent_review.text
    assert urgent_review.json()["status"] == "published"
    assert any(
        signal["id"] == urgent_signal["id"]
        for signal in client.get(
            "/api/v1/marine-signals/signals", headers=auth_headers(office)
        ).json()
    )

    assert client.get(
        "/api/v1/marine-signals/signals?include_review=true",
        headers=auth_headers(other_tenant),
    ).json() == []
    assert service_db.execute(
        text(
            """
            SELECT count(*) FROM outbox_events
            WHERE company_id = :company_id AND event_type = 'marine_signal.urgent_alert'
            """
        ),
        {"company_id": company_id},
    ).scalar_one() == 1

    service_db.execute(
        text(
            """
            UPDATE marine_signal_sources
            SET last_checked_at = now(), last_error = 'feed failed'
            WHERE company_id = :company_id AND id = :source_id
            """
        ),
        {"company_id": company_id, "source_id": source["id"]},
    )
    service_db.commit()
    metrics = client.get(
        "/api/v1/marine-signals/metrics", headers=auth_headers(owner)
    ).json()
    assert metrics["fresh_sources"] == 0
    assert metrics["stale_sources"] == 1


def test_feed_refresh_upserts_a_reviewed_signal(client, app_db, monkeypatch):
    owner = signup(client)
    source = _create_source(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])
    feed = [
        b"<rss><channel><item><guid>stable-entry</guid><title>Original</title>"
        b"<description>Original details</description></item></channel></rss>",
        b"<rss><channel><item><guid>stable-entry</guid><title>Updated</title>"
        b"<description>Updated details</description></item></channel></rss>",
    ]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield feed[0]

    class FakeClient:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(marine_signals.httpx, "Client", FakeClient)
    set_tenant(app_db, company_id)
    assert marine_signals.refresh_source(
        app_db, company_id, uuid.UUID(source["id"])
    ) == 1
    app_db.commit()
    set_tenant(app_db, company_id)
    signal_id = app_db.execute(
        text(
            """
            SELECT id FROM marine_signals
            WHERE company_id = :company_id AND external_id = 'stable-entry'
            """
        ),
        {"company_id": company_id},
    ).scalar_one()
    app_db.commit()

    reviewed = _review_signal(client, owner, str(signal_id))
    assert reviewed.status_code == 200, reviewed.text
    feed[0] = feed[1]
    set_tenant(app_db, company_id)
    assert marine_signals.refresh_source(
        app_db, company_id, uuid.UUID(source["id"])
    ) == 1
    app_db.commit()
    set_tenant(app_db, company_id)
    rows = app_db.execute(
        text(
            """
            SELECT title, status, reviewed_at FROM marine_signals
            WHERE company_id = :company_id AND external_id = 'stable-entry'
            """
        ),
        {"company_id": company_id},
    ).all()
    assert len(rows) == 1
    assert rows[0].title == "Updated"
    assert rows[0].status == "needs_review"
    assert rows[0].reviewed_at is None


def test_digest_failure_releases_claim_and_retry_uses_review_time(
    client, app_engine, service_engine, service_db, monkeypatch
):
    owner = signup(client)
    source = _create_source(client, owner)
    old_publication = datetime.now(timezone.utc) - timedelta(days=30)
    signal = _create_signal(
        client, owner, source["id"], "Recently reviewed old bulletin", old_publication
    )
    profile = client.put(
        "/api/v1/marine-signals/profile",
        json={
            "digest_email": "digest@example.com",
            "digest_enabled": True,
        },
        headers=auth_headers(owner),
    )
    assert profile.status_code == 200, profile.text
    reviewed = _review_signal(client, owner, signal["id"])
    assert reviewed.status_code == 200, reviewed.text

    monkeypatch.setattr(
        sweep,
        "AppSession",
        sessionmaker(bind=app_engine, class_=Session, expire_on_commit=False),
    )
    monkeypatch.setattr(
        sweep,
        "ServiceSession",
        sessionmaker(bind=service_engine, class_=Session, expire_on_commit=False),
    )
    attempts = []

    def fail_then_send(*_args):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("temporary mail failure")
        return True

    monkeypatch.setattr(marine_signals, "send_digest_email", fail_then_send)
    first = sweep.send_weekly_digests(datetime.now(timezone.utc))
    assert first["failed"] == 1
    company_id = owner["user"]["company_id"]
    assert service_db.execute(
        text(
            """
            SELECT count(*) FROM marine_signal_digest_deliveries
            WHERE company_id = :company_id
            """
        ),
        {"company_id": company_id},
    ).scalar_one() == 0

    retry = sweep.send_weekly_digests(datetime.now(timezone.utc))
    assert retry["sent"] == 1
    assert len(attempts) == 2
    delivery = service_db.execute(
        text(
            """
            SELECT status FROM marine_signal_digest_deliveries
            WHERE company_id = :company_id
            """
        ),
        {"company_id": company_id},
    ).scalar_one()
    assert delivery == "sent"
