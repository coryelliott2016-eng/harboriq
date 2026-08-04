"""Address geocoding: free-text address -> (latitude, longitude).

Provider: **OpenStreetMap Nominatim** (`https://nominatim.openstreetmap.org
/search`) — chosen because it is free, requires no API key/account, and
needs zero configuration to work in this workspace today (no Google
Maps/Mapbox connector is set up). The trade-offs are real and worth naming:
Nominatim's usage policy caps free/anonymous use at *1 request/second* and
asks for a descriptive `User-Agent` identifying the calling application
(https://operations.osmfoundation.org/policies/nominatim/) — both honored
below — and its match quality/coverage is generally a notch below a paid
provider for messy or very new addresses.

--------------------------------------------------------------------------
SWAP POINT for Google Maps / Mapbox (read this before adding a new provider)
--------------------------------------------------------------------------
Every caller in this codebase (`app/services/users.py`, `app/services/
customers.py`, `app/jobs/geocode_backfill.py`) depends ONLY on the
module-level `geocode(address) -> tuple[Decimal, Decimal] | None` function
below — never on Nominatim, `httpx`, or any provider-specific detail. To
switch providers later (e.g. once the user connects a Google Maps/Mapbox
API key), the entire change is contained to this one file:

  1. Add the new provider's API key to `app/core/config.py` (following the
     same optional/empty-string-means-disabled pattern `stripe_api_key` and
     `smtp_host` already use elsewhere in that file).
  2. Replace the body of `_call_nominatim()` (or add a `_call_google()` /
     `_call_mapbox()` alongside it and branch on which API key is set) with
     the new HTTP call, keeping the same return shape:
     `tuple[Decimal, Decimal] | None`.
  3. Leave `geocode()`'s signature, graceful-degradation contract (never
     raises; returns `None` on any failure), and rate-limiting behavior
     unchanged so every call site keeps working with no further edits.

No call site should ever be touched for a provider swap — if a change here
requires editing `users.py`/`customers.py`/the backfill job too, the
abstraction boundary has leaked and should be fixed first.
"""
from __future__ import annotations

import threading
import time
from decimal import Decimal, InvalidOperation

import httpx
import structlog

logger = structlog.get_logger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

#: Nominatim's usage policy requires a descriptive User-Agent identifying the
#: application (not a generic HTTP client string) —
#: https://operations.osmfoundation.org/policies/nominatim/
_USER_AGENT = "HarborIQ/1.0 (marine service SaaS; https://github.com/coryelliott2016-eng/harboriq)"

#: Nominatim's free/anonymous tier is rate-limited to 1 request/second. This
#: is an in-process sleep-based limiter, not a distributed one — proportionate
#: for now because geocoding is triggered by individual admin/user actions
#: (a profile save, a customer create/update), not high-volume traffic. A
#: multi-instance deployment doing heavy backfills would need a shared
#: (e.g. Redis-backed) limiter instead; see `app/jobs/geocode_backfill.py`
#: for how a bulk caller reuses this same per-process throttle.
_MIN_INTERVAL_SECONDS = 1.0

_HTTP_TIMEOUT_SECONDS = 5.0

_lock = threading.Lock()
_last_call_monotonic: float | None = None


def _throttle() -> None:
    """Block just long enough to keep calls at least 1 second apart.

    Guarded by a lock so concurrent callers within one process still respect
    the shared rate limit rather than each independently sleeping and firing
    in the same instant.
    """
    global _last_call_monotonic
    with _lock:
        now = time.monotonic()
        if _last_call_monotonic is not None:
            elapsed = now - _last_call_monotonic
            wait = _MIN_INTERVAL_SECONDS - elapsed
            if wait > 0:
                time.sleep(wait)
        _last_call_monotonic = time.monotonic()


def _parse_coordinates(result: dict) -> tuple[Decimal, Decimal] | None:
    try:
        lat = Decimal(str(result["lat"]))
        lon = Decimal(str(result["lon"]))
    except (KeyError, InvalidOperation, TypeError):
        return None
    return lat, lon


def _call_nominatim(address: str) -> tuple[Decimal, Decimal] | None:
    """One throttled HTTPS call to Nominatim. Never raises."""
    _throttle()
    try:
        response = httpx.get(
            NOMINATIM_URL,
            params={"q": address, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("geocoding.request_failed", address=address, error=str(exc))
        return None

    if response.status_code != 200:
        logger.warning(
            "geocoding.non_200_response",
            address=address,
            status_code=response.status_code,
        )
        return None

    try:
        results = response.json()
    except ValueError:
        logger.warning("geocoding.invalid_json_response", address=address)
        return None

    if not results:
        logger.info("geocoding.no_match", address=address)
        return None

    return _parse_coordinates(results[0])


def geocode(address: str) -> tuple[Decimal, Decimal] | None:
    """Resolve a free-text address to (latitude, longitude), or None.

    Graceful degradation is the whole contract here: a timeout, a non-200
    response, an empty result set, or a blank/whitespace-only address all
    return `None` rather than raising. Every caller in this codebase treats
    `None` the same way the dispatch engine already treats missing
    coordinates elsewhere — save the record anyway, leave lat/lng NULL, move
    on. Geocoding must never be the reason a save fails.
    """
    address = (address or "").strip()
    if not address:
        return None

    try:
        return _call_nominatim(address)
    except Exception:  # noqa: BLE001 - a geocoding failure must never bubble up.
        logger.exception("geocoding.unexpected_error", address=address)
        return None
