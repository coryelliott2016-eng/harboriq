"""Shared FastAPI dependencies.

Tenant context is derived from a verified Bearer access token — never from a
client-supplied header. `get_current_user` decodes the JWT, re-reads the user
row under RLS, and arms `app.current_company_id` for the rest of the request,
so the existing TenantContext/RLS machinery is driven by authenticated input.

The token carries a `role` claim, but authorization reads the role from the
database row instead. That costs one indexed lookup per request and buys
immediate effect for deactivations and role changes, rather than waiting for
the access token to expire.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import InvalidToken, decode_access_token
from app.core.token_denylist import is_denylisted
from app.db.models import OPERATIONS_ROLES, USER_MANAGEMENT_ROLES, UserRole
from app.db.session import get_db, get_service_db
from app.db.tenant import set_tenant
from app.services.auth import AuthenticatedUser, load_user

# auto_error=False so a missing header produces our own 401 shape rather than
# FastAPI's 403.
_bearer_scheme = HTTPBearer(auto_error=False, description="Bearer access token")


@dataclass(frozen=True)
class Principal:
    """The authenticated caller plus the session its access token came from."""

    user: AuthenticatedUser
    session_id: uuid.UUID
    token_jti: str
    token_expires_at: datetime


def _unauthenticated(detail: str = "not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    """Verify the Bearer token, load the user under RLS, and arm the tenant GUC."""
    if credentials is None or not credentials.credentials:
        raise _unauthenticated()

    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidToken as exc:
        raise _unauthenticated(f"invalid access token: {exc}") from exc

    if is_denylisted(claims.jti):
        raise _unauthenticated("access token has been revoked")

    user = load_user(db, claims.company_id, claims.user_id)
    if user is None or not user.is_active:
        raise _unauthenticated("account is not active")

    set_tenant(db, user.company_id)
    return Principal(
        user=user,
        session_id=claims.session_id,
        token_jti=claims.jti,
        token_expires_at=claims.expires_at,
    )


def get_current_user(
    principal: Principal = Depends(get_current_principal),
) -> AuthenticatedUser:
    return principal.user


def get_current_company_id(
    user: AuthenticatedUser = Depends(get_current_user),
) -> uuid.UUID:
    """The acting tenant, derived from the verified token."""
    return user.company_id


def require_roles(*roles: UserRole) -> Callable[..., AuthenticatedUser]:
    """Dependency factory enforcing that the caller holds one of `roles`."""
    allowed = {UserRole(role).value for role in roles}

    def dependency(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of these roles: {sorted(allowed)}",
            )
        return user

    return dependency


#: Only owners and admins may provision other users.
require_user_manager = require_roles(*USER_MANAGEMENT_ROLES)

#: Alias for owner/admin-gated billing-admin actions (Stripe Connect
#: onboarding, running the dunning sweep on demand). Same role set as
#: `require_user_manager` -- kept as a separate name because "who may manage
#: teammates" and "who may manage billing/payments configuration" are
#: different concerns that happen to share a role set today; a future phase
#: could split them (e.g. a dedicated billing-admin role) without touching
#: user-management call sites.
require_admin = require_roles(*USER_MANAGEMENT_ROLES)

#: Front-of-house work — the customer book, the fleet, and dispatching jobs.
#: Technicians are excluded here and are granted narrower access per-endpoint.
require_operations = require_roles(*OPERATIONS_ROLES)

#: Role values that may act on any job in the tenant. Compared against
#: `AuthenticatedUser.role`, which is a plain string.
OPERATIONS_ROLE_VALUES = frozenset(role.value for role in OPERATIONS_ROLES)


def authorize_job_action(
    db: Session, user: AuthenticatedUser, job_id: uuid.UUID
) -> None:
    """Allow the action if the caller runs the shop or owns this work order.

    Owner/admin/office short-circuit without a query. For anyone else the job is
    loaded under RLS first, so a technician probing another tenant's id gets the
    same 404 as for an id that does not exist, rather than a 403 that would
    confirm the job is real.
    """
    if user.role in OPERATIONS_ROLE_VALUES:
        return

    # Imported here: the jobs service pulls in the state machines and schemas,
    # and deps is imported by every route module.
    from app.api.errors import http_errors
    from app.services import jobs as jobs_service

    with http_errors():
        job = jobs_service.get(db, user.company_id, job_id)
    if job.technician_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the assigned technician or an office user may act on this job",
        )


__all__ = [
    "OPERATIONS_ROLE_VALUES",
    "Principal",
    "authorize_job_action",
    "get_current_company_id",
    "get_current_principal",
    "get_current_user",
    "get_db",
    "get_service_db",
    "require_admin",
    "require_operations",
    "require_roles",
    "require_user_manager",
]
