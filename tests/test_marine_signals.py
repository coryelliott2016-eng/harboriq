"""Marine Signals source validation and feed parsing tests."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.marine_signals import MarineSignalCreate, MarineSignalReview, MarineSignalSourceCreate
from app.services.marine_signals import _parse_feed
from app.services.outbox import _build_email


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
        )

    with pytest.raises(ValidationError):
        MarineSignalCreate(
            source_id="9d95aa92-28fc-4436-b457-d6d9f6e81157",
            category="weather",
            title="Outlook",
            citation_url="https://www.weather.gov/tbw/outlook",
            published_at="2026-10-05T12:00:00",
        )
