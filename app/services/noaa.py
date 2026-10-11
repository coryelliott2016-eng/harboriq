"""Bounded NOAA HTTPS adapter; never synthesizes missing or stale observations."""
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from app.schemas.intelligence import Measurement

NOAA_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
STATIONS = {
    "8726520": "St. Petersburg",
    "8518750": "The Battery",
    "9414290": "San Francisco",
}
MAX_BYTES = 65536
MAX_AGE = timedelta(hours=2)
NUMBER = re.compile(r"[+-]?\d{1,6}(?:\.\d{1,8})?")


class NOAAUnavailable(Exception):
    """Only sanitized errors cross the public API boundary."""


@dataclass(frozen=True)
class Observation:
    source_url: str
    retrieved_at: datetime
    observed_at: datetime
    measurements: list[Measurement]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate NOAA field")
        result[key] = value
    return result


def _parse(raw: bytes, station: str, source_url: str, now: datetime) -> Observation:
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("NOAA error")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("id") != station:
            raise ValueError("Wrong NOAA station")
        data = payload.get("data")
        if not isinstance(data, list) or not 1 <= len(data) <= 20:
            raise ValueError("Missing observations")
        measurements = []
        times = []
        for row in data:
            if not isinstance(row, dict):
                raise ValueError("Malformed observation")
            value, timestamp = row.get("v"), row.get("t")
            if "q" in row and row["q"] not in ("p", "v"):
                raise ValueError("Invalid observation quality")
            if "f" in row and row["f"] != "0,0,0,0":
                raise ValueError("Flagged or malformed observation")
            if not isinstance(value, str) or not NUMBER.fullmatch(value):
                raise ValueError("Invalid measurement")
            number = Decimal(value)
            if not number.is_finite() or abs(number) > 100:
                raise ValueError("Invalid measurement")
            if not isinstance(timestamp, str) or len(timestamp) != 16:
                raise ValueError("Invalid timestamp")
            observed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            if now - observed > MAX_AGE or observed - now > timedelta(minutes=5):
                raise ValueError("Stale or future observation")
            times.append(observed)
            measurements.append(Measurement(time=observed.isoformat(), value=value, unit="ft MLLW"))
        if len(set(times)) != len(times):
            raise ValueError("Duplicate observations")
        measurements.sort(key=lambda item: item.time)
        return Observation(source_url, now, max(times), measurements)
    except (ValueError, TypeError, KeyError, InvalidOperation, RecursionError) as exc:
        raise NOAAUnavailable("NOAA returned unavailable or invalid observations.") from exc


def fetch_water_level(station: str, *, transport=None) -> Observation:
    if station not in STATIONS:
        raise NOAAUnavailable("Unsupported station.")
    params = {
        "product": "water_level", "station": station, "date": "latest",
        "datum": "MLLW", "time_zone": "gmt", "units": "english",
        "format": "json", "application": "HarborIQ_public_demo",
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(5, connect=3), follow_redirects=False,
            transport=transport, trust_env=False,
        ) as client:
            with client.stream(
                "GET", NOAA_URL, params=params, headers={"Accept-Encoding": "identity"},
            ) as response:
                if response.status_code != 200:
                    raise NOAAUnavailable("NOAA is temporarily unavailable.")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise NOAAUnavailable("NOAA returned unsupported encoding.")
                raw = bytearray()
                for chunk in response.iter_raw(chunk_size=4096):
                    if len(raw) + len(chunk) > MAX_BYTES or time.monotonic() - started > 10:
                        raise NOAAUnavailable("NOAA response exceeded demo limits.")
                    raw.extend(chunk)
                return _parse(bytes(raw), station, str(response.request.url), datetime.now(UTC))
    except httpx.HTTPError as exc:
        raise NOAAUnavailable("NOAA is temporarily unavailable.") from exc
