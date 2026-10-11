from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services import noaa

pytestmark = pytest.mark.no_db


def payload(value="1.234", timestamp=None):
    return {
        "metadata": {"id": "8726520", "name": "Untrusted name"},
        "data": [{"t": timestamp or datetime.now(UTC).strftime("%Y-%m-%d %H:%M"), "v": value}],
    }


class Stream(httpx.SyncByteStream):
    def __init__(self, content):
        self.content = content

    def __iter__(self):
        yield self.content


def transport_for(data=None, *, raw=None, status=200, headers=None):
    import json

    content = raw if raw is not None else json.dumps(data).encode()
    return httpx.MockTransport(
        lambda request: httpx.Response(status, headers=headers, stream=Stream(content))
    )


def test_latest_request_has_fixed_source_and_explicit_units():
    result = noaa.fetch_water_level("8726520", transport=transport_for(payload()))
    url = urlparse(result.source_url)
    assert f"{url.scheme}://{url.netloc}{url.path}" == noaa.NOAA_URL
    params = parse_qs(url.query)
    assert params == {
        "product": ["water_level"], "station": ["8726520"], "date": ["latest"],
        "datum": ["MLLW"], "time_zone": ["gmt"], "units": ["english"],
        "format": ["json"], "application": ["HarborIQ_public_demo"],
    }
    assert result.measurements[0].value == "1.234"
    assert result.measurements[0].unit == "ft MLLW"
    assert result.observed_at.tzinfo == UTC
    assert result.retrieved_at >= result.observed_at - timedelta(minutes=5)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "", "1e999", "1000", None, 2, True])
def test_rejects_invalid_numbers(value):
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("8726520", transport=transport_for(payload(value)))


@pytest.mark.parametrize("offset", [-121, 10])
def test_rejects_stale_or_future_observations(offset):
    timestamp = (datetime.now(UTC) + timedelta(minutes=offset)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("8726520", transport=transport_for(payload(timestamp=timestamp)))


@pytest.mark.parametrize("data", [
    None, [], {"error": {"message": "upstream private error"}},
    {"metadata": {"id": "8518750"}, "data": []},
    {"metadata": {"id": "8726520"}, "data": [None]},
    {"metadata": {"id": "8726520"}, "data": "unexpected"},
])
def test_rejects_error_or_malformed_structure(data):
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("8726520", transport=transport_for(data))


@pytest.mark.parametrize("raw", [b"not json", b'{"data": [], "data": []}', b"x" * 65537])
def test_rejects_bad_json_or_oversize_stream(raw):
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("8726520", transport=transport_for(raw=raw))


@pytest.mark.parametrize("timestamp", [
    "2026-01-01", "2026-01-01 00:00Z", "invalid timestamp", "2026-99-99 99:99",
])
def test_rejects_invalid_timezone_or_timestamp(timestamp):
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("8726520", transport=transport_for(payload(timestamp=timestamp)))


@pytest.mark.parametrize("status", [301, 429, 500])
def test_does_not_follow_redirect_or_accept_upstream_failure(status):
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("8726520", transport=transport_for(payload(), status=status))


def test_does_not_decode_compression_bombs():
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level(
            "8726520", transport=transport_for(raw=b"x", headers={"Content-Encoding": "gzip"}),
        )


def test_timeout_is_sanitized():
    def timeout(request):
        raise httpx.ReadTimeout("sensitive upstream details", request=request)

    with pytest.raises(noaa.NOAAUnavailable, match="temporarily unavailable"):
        noaa.fetch_water_level("8726520", transport=httpx.MockTransport(timeout))


def test_unknown_station_does_not_make_network_call():
    def forbidden(request):
        pytest.fail("Unsupported station must not call NOAA")

    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("https://evil.example", transport=httpx.MockTransport(forbidden))


@pytest.mark.parametrize("fields", [
    {"q": "unknown"}, {"q": None}, {"f": "1,0,0,0"}, {"f": None}, {"f": ["0"]},
])
def test_rejects_flagged_or_invalid_quality_observations(fields):
    data = payload()
    data["data"][0].update(fields)
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("8726520", transport=transport_for(data))


@pytest.mark.parametrize("quality", ["p", "v"])
def test_accepts_noaa_quality_labels_with_zero_flags(quality):
    data = payload()
    data["data"][0].update({"q": quality, "f": "0,0,0,0"})
    assert noaa.fetch_water_level("8726520", transport=transport_for(data)).measurements


def test_rejects_duplicate_measurement_timestamps():
    data = payload()
    data["data"].append(data["data"][0].copy())
    with pytest.raises(noaa.NOAAUnavailable):
        noaa.fetch_water_level("8726520", transport=transport_for(data))


def test_total_stream_deadline_is_bounded(monkeypatch):
    ticks = iter([0, 11])
    monkeypatch.setattr(noaa.time, "monotonic", lambda: next(ticks))
    with pytest.raises(noaa.NOAAUnavailable, match="exceeded demo limits"):
        noaa.fetch_water_level("8726520", transport=transport_for(payload()))
