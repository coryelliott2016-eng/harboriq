"""Self-service + admin user profile editing (`PATCH /users/{id}`, Phase 10).

Two distinct permission surfaces share one route:

- **Self-edit**: any authenticated user may update their own `full_name`,
  `skills`, and `address_text` (which triggers geocoding into
  `home_latitude`/`home_longitude`). They may NOT touch their own `role` or
  `is_active` — that would let a technician promote themselves.
- **Admin-edit**: an owner/admin (`require_admin`, i.e. `USER_MANAGEMENT_
  ROLES`) may update any of those same fields PLUS `role`/`is_active` for
  ANY user in their own company (never `password_hash`/`mfa_secret_enc`,
  which have their own dedicated flows already — password reset and a
  not-yet-built MFA enrollment flow, respectively).

Tenant isolation is enforced the same way every other service in this
package enforces it: all reads/writes happen inside `tenant_context`, so RLS
makes "belongs to another tenant" indistinguishable from "does not exist" —
both surface as 404, leaking nothing about whether the id exists elsewhere.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import USER_MANAGEMENT_ROLES
from app.db.tenant import tenant_context
from app.services import geocoding
from app.services.crud import Conflict, NotFound, ValidationFailed, assignments

logger = structlog.get_logger(__name__)

#: Fields any user may change about themselves.
SELF_EDITABLE_COLUMNS = frozenset({"full_name", "skills", "address_text"})

#: Additional fields only an admin may change, and only for someone else
#: (or, in principle, themselves — an owner/admin editing their own row via
#: the admin path is allowed since they already hold that role).
#: `hourly_rate` (Phase 14, migration 0013) joins this set rather than
#: `SELF_EDITABLE_COLUMNS` for the same reason `role` does: a technician
#: setting their own pay rate would make the P&L labor-cost figure
#: self-reported and untrustworthy.
ADMIN_ONLY_COLUMNS = frozenset({"role", "is_active", "hourly_rate"})

#: The full set of columns `PATCH /users/{id}` may ever write. Geocoding
#: derives `home_latitude`/`home_longitude` server-side from `address_text`
#: and is never accepted directly from the request body.
UPDATABLE_COLUMNS = SELF_EDITABLE_COLUMNS | ADMIN_ONLY_COLUMNS


class FieldNotPermitted(Exception):
    """Caller attempted to change a field their role does not allow."""


def _map_integrity_error(exc: IntegrityError) -> Exception | None:
    detail = str(exc.orig)
    if "uq_users_company_email" in detail or "uq_users_email_global" in detail:
        return Conflict("email already in use")
    if "ck_users_home_latlng_pair" in detail:
        return ValidationFailed("home coordinates must be set or cleared together")
    return None


def get(db: Session, company_id: uuid.UUID, user_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id}).first()
    if row is None:
        raise NotFound(f"user {user_id} not found")
    return row


def list_users(db: Session, company_id: uuid.UUID) -> list[Row]:
    """Every user in the caller's company — the team roster."""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM users
                     WHERE company_id = :cid
                     ORDER BY role, full_name NULLS LAST, email
                    """
                ),
                {"cid": company_id},
            ).all()
        )


def update_profile(
    db: Session,
    company_id: uuid.UUID,
    *,
    target_user_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_role: str,
    changes: dict[str, Any],
) -> Row:
    """Apply a profile PATCH, enforcing self-vs-admin field permissions.

    `changes` has already been trimmed of unset fields by the route (a
    Pydantic `exclude_unset=True` dump) — only keys the caller actually
    supplied are present, so a technician omitting `role` entirely is fine;
    a technician explicitly sending `role` is rejected.
    """
    is_admin = actor_role in {r.value for r in USER_MANAGEMENT_ROLES}
    is_self = actor_user_id == target_user_id

    if not is_admin and not is_self:
        # Should never be reachable if the route checks this first, but the
        # service does not trust its caller to have remembered to.
        raise FieldNotPermitted("cannot edit another user's profile")

    allowed = UPDATABLE_COLUMNS if is_admin else SELF_EDITABLE_COLUMNS
    disallowed = set(changes) - allowed
    if disallowed:
        raise FieldNotPermitted(
            f"not permitted to change: {sorted(disallowed)}"
        )

    if not changes:
        return get(db, company_id, target_user_id)

    # Geocode a new/changed home address. Graceful degradation: a geocoding
    # failure never blocks the save — the address text is written either
    # way, and coordinates are simply left as whatever `geocode()` returned
    # (None -> NULL, clearing any previously-set coordinates for the new
    # address, which is correct: stale coordinates from the OLD address must
    # not linger under the new address text).
    if "address_text" in changes:
        address = changes["address_text"]
        if address:
            result = geocoding.geocode(address)
            changes["home_latitude"], changes["home_longitude"] = (
                result if result is not None else (None, None)
            )
        else:
            changes["home_latitude"], changes["home_longitude"] = None, None

    write_columns = UPDATABLE_COLUMNS | {"home_latitude", "home_longitude"}
    # Note: unlike customers/companies, `users` has no `updated_at` column
    # (see app/db/models.py) -- so this UPDATE, unlike the analogous one in
    # app/services/customers.py, does not touch it.
    statement = text(
        f"""
        UPDATE users
           SET {assignments(changes, write_columns)}
         WHERE id = :id
        RETURNING *
        """
    )
    try:
        with tenant_context(db, company_id):
            row = db.execute(statement, changes | {"id": target_user_id}).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        mapped = _map_integrity_error(exc)
        if mapped is None:
            raise
        raise mapped from exc

    if row is None:
        raise NotFound(f"user {target_user_id} not found")
    return row


@dataclass(frozen=True)
class LocationPingResult:
    """Service-layer result for one location ping (route maps to LocationPingOut)."""

    id: uuid.UUID
    current_latitude: Any
    current_longitude: Any
    location_updated_at: datetime
    anomaly_suspected: bool = False
    implied_speed_kmh: float | None = None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS84 points."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _evaluate_location_anomaly(
    *,
    prev_lat,
    prev_lng,
    prev_updated_at: datetime | None,
    new_lat,
    new_lng,
    now: datetime,
) -> tuple[bool, float | None]:
    """Return (anomaly_suspected, implied_speed_kmh).

    Flag-only: never rejects the ping. A missing/stale prior fix is treated as
    a fresh trip (no anomaly). Marine threat model Scenario 2 (2026-08-11).
    """
    if prev_lat is None or prev_lng is None or prev_updated_at is None:
        return False, None
    if prev_updated_at.tzinfo is None:
        prev_updated_at = prev_updated_at.replace(tzinfo=timezone.utc)
    elapsed_s = (now - prev_updated_at).total_seconds()
    if elapsed_s <= 0:
        # Clock skew or same-timestamp double-submit: treat as zero elapsed
        # and only flag if the points themselves are far apart (handled by
        # the tiny-elapsed branch below via a 1s floor).
        elapsed_s = 1.0
    if elapsed_s > settings.location_ping_plausibility_window_seconds:
        return False, None
    distance_km = _haversine_km(
        float(prev_lat), float(prev_lng), float(new_lat), float(new_lng)
    )
    speed_kmh = distance_km / (elapsed_s / 3600.0)
    # Short hops are dominated by GPS jitter / sub-second double-submits and
    # must not raise a teleport alert even when the implied speed is huge.
    # 5 km is well above consumer-GPS noise and well below a real spoofed
    # cross-city jump.
    min_distance_km = 5.0
    anomaly = (
        distance_km >= min_distance_km
        and speed_kmh > settings.location_ping_max_plausible_speed_kmh
    )
    return anomaly, round(speed_kmh, 2)


def ping_location(
    db: Session,
    company_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    latitude,
    longitude,
) -> LocationPingResult:
    """Record one `POST /users/me/location-ping` reading (Phase 11).

    Always self-service: a technician can only ever ping their OWN location
    (the route passes `user_id` from the authenticated principal, never from
    the request body), so there is no separate admin path to guard here the
    way `update_profile` must for `role`/`is_active`.

    Reads the prior fix first so an implied-speed plausibility check can flag
    teleport-style spoofs (flagged on the response + structured log; the new
    coordinates are still accepted so a legitimate GPS cold-start jump is
    never a hard failure).
    """
    now = datetime.now(timezone.utc)
    with tenant_context(db, company_id):
        prev = db.execute(
            text(
                """
                SELECT current_latitude, current_longitude, location_updated_at
                  FROM users
                 WHERE id = :id
                """
            ),
            {"id": user_id},
        ).first()
        if prev is None:
            raise NotFound(f"user {user_id} not found")

        anomaly, speed_kmh = _evaluate_location_anomaly(
            prev_lat=prev.current_latitude,
            prev_lng=prev.current_longitude,
            prev_updated_at=prev.location_updated_at,
            new_lat=latitude,
            new_lng=longitude,
            now=now,
        )
        if anomaly:
            logger.warning(
                "location_ping.anomaly_suspected",
                user_id=str(user_id),
                company_id=str(company_id),
                implied_speed_kmh=speed_kmh,
                prev_lat=float(prev.current_latitude) if prev.current_latitude is not None else None,
                prev_lng=float(prev.current_longitude) if prev.current_longitude is not None else None,
                new_lat=float(latitude),
                new_lng=float(longitude),
                prev_updated_at=(
                    prev.location_updated_at.isoformat()
                    if prev.location_updated_at is not None
                    else None
                ),
            )

        row = db.execute(
            text(
                """
                UPDATE users
                   SET current_latitude = :lat,
                       current_longitude = :lng,
                       location_updated_at = :ts
                 WHERE id = :id
                RETURNING id, current_latitude, current_longitude, location_updated_at
                """
            ),
            {"lat": latitude, "lng": longitude, "id": user_id, "ts": now},
        ).first()
        db.commit()
    if row is None:
        raise NotFound(f"user {user_id} not found")
    return LocationPingResult(
        id=row.id,
        current_latitude=row.current_latitude,
        current_longitude=row.current_longitude,
        location_updated_at=row.location_updated_at,
        anomaly_suspected=anomaly,
        implied_speed_kmh=speed_kmh,
    )


def list_technician_locations(db: Session, company_id: uuid.UUID) -> list[Row]:
    """Every technician's best-known position for the dispatch board map.

    Falls back to the static home base (`home_latitude`/`home_longitude`,
    set via geocoded `address_text`) when no ping has ever landed, and
    reports whether the coordinates are live so the map/legend never implies
    more freshness than the data actually has (see `TechnicianLocationOut`).
    """
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT id,
                           full_name,
                           COALESCE(current_latitude, home_latitude) AS latitude,
                           COALESCE(current_longitude, home_longitude) AS longitude,
                           (current_latitude IS NOT NULL) AS is_live,
                           location_updated_at
                      FROM users
                     WHERE company_id = :cid
                       AND role = 'technician'
                       AND is_active
                     ORDER BY full_name NULLS LAST, email
                    """
                ),
                {"cid": company_id},
            ).all()
        )
