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

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import USER_MANAGEMENT_ROLES
from app.db.tenant import tenant_context
from app.services import geocoding
from app.services.crud import Conflict, NotFound, ValidationFailed, assignments

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


def ping_location(
    db: Session,
    company_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    latitude,
    longitude,
) -> Row:
    """Record one `POST /users/me/location-ping` reading (Phase 11).

    Always self-service: a technician can only ever ping their OWN location
    (the route passes `user_id` from the authenticated principal, never from
    the request body), so there is no separate admin path to guard here the
    way `update_profile` must for `role`/`is_active`.
    """
    with tenant_context(db, company_id):
        row = db.execute(
            text(
                """
                UPDATE users
                   SET current_latitude = :lat,
                       current_longitude = :lng,
                       location_updated_at = now()
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"lat": latitude, "lng": longitude, "id": user_id},
        ).first()
        db.commit()
    if row is None:
        raise NotFound(f"user {user_id} not found")
    return row


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
