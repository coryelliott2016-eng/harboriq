"""Team roster + self-service/admin profile editing (Phase 10).

`GET /users` — the team roster: every user in the caller's company. Gated
at `require_operations` (owner/admin/office) — the same bar the frontend
`/team` page enforces to VIEW the roster; front-of-house staff reasonably
need to see who's on the team and their skills/availability signal (home
coordinates set or not) without being able to edit anyone.

`PATCH /users/{id}` — see `app/services/users.py` for the full self-vs-admin
permission writeup. `{id}` may be the caller's own id (self-edit, any
authenticated user) or another user's id in the same company (admin-edit,
`require_admin` only).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_company_id,
    get_current_user,
    get_db,
    require_operations,
)
from app.api.errors import http_errors
from app.schemas.auth import TeamMemberOut, UserUpdate
from app.schemas.dispatch_board import (
    LocationPing,
    LocationPingOut,
    TechnicianLocationOut,
)
from app.services import users as users_service
from app.services.auth import AuthenticatedUser
from app.services.users import FieldNotPermitted

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[TeamMemberOut], dependencies=[Depends(require_operations)])
def list_team(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """The team roster: every user in the caller's company."""
    rows = users_service.list_users(db, company_id)
    return [TeamMemberOut.model_validate(row) for row in rows]


@router.patch("/{user_id}", response_model=TeamMemberOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    actor: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service profile edit, or an admin editing a teammate.

    A non-admin may only pass `user_id == actor.id` — anything else is a 403
    before the service layer is even consulted, so "editing someone else
    without permission" and "that user doesn't exist" are never confused
    with each other's error paths.
    """
    is_admin = actor.role in {"owner", "admin"}
    if not is_admin and user_id != actor.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "you may only edit your own profile",
        )

    changes = body.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] is not None:
        changes["role"] = changes["role"].value

    try:
        with http_errors():
            row = users_service.update_profile(
                db,
                actor.company_id,
                target_user_id=user_id,
                actor_user_id=actor.id,
                actor_role=actor.role,
                changes=changes,
            )
    except FieldNotPermitted as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    return TeamMemberOut.model_validate(row)


@router.post("/me/location-ping", response_model=LocationPingOut)
def ping_my_location(
    body: LocationPing,
    actor: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record the caller's current position (Phase 11 dispatch board map).

    Any authenticated technician may ping their OWN location — there is no
    `user_id` in the request; it always comes from the auth token. This is
    best-effort: the frontend calls this every few minutes while a
    technician has the staff web app open and has granted the browser's
    Geolocation permission (see `frontend/src/hooks/useLocationPing.ts`).
    It is NOT background tracking — closing the tab or the browser stops
    pings immediately, and there is no mobile app yet. True background
    tracking is deliberately out of scope for this phase (Phase 12).
    """
    with http_errors():
        row = users_service.ping_location(
            db,
            actor.company_id,
            user_id=actor.id,
            latitude=body.latitude,
            longitude=body.longitude,
        )
    return LocationPingOut.model_validate(row)


@router.get(
    "/technician-locations",
    response_model=list[TechnicianLocationOut],
    dependencies=[Depends(require_operations)],
)
def list_technician_locations(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Every technician's best-known position, for the dispatch board map.

    Gated the same as the roster (`require_operations`) — knowing where the
    team physically is right now is shop-management information, same tier
    as the roster itself.
    """
    rows = users_service.list_technician_locations(db, company_id)
    return [TechnicianLocationOut.model_validate(row) for row in rows]
