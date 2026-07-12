"""Tenant context — sets the PostgreSQL session variable RLS policies read.

Usage:
    with tenant_context(db, company_id):
        db.query(Invoice).all()   # RLS auto-filters by company_id

For background jobs/webhooks that run outside an HTTP request, pass company_id
explicitly. Public routes resolve company_id from a token via the service role
FIRST, then enter tenant_context for the actual action.
"""
from collections.abc import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class TenantContext:
    """Context manager that sets app.current_company_id for the current tx."""

    def __init__(self, db: Session, company_id: UUID | str):
        self.db = db
        self.company_id = str(company_id)
        self._owned = False

    def __enter__(self) -> "TenantContext":
        # set_config(name, value, is_local=true) sets a transaction-scoped GUC.
        # SET LOCAL cannot take bind parameters; set_config() can.
        self.db.execute(
            text("SELECT set_config('app.current_company_id', :cid, true)"),
            {"cid": self.company_id},
        )
        return self

    def __exit__(self, *exc) -> None:
        # SET LOCAL resets at transaction end; nothing required.
        pass


def tenant_context(db: Session, company_id: UUID | str) -> TenantContext:
    return TenantContext(db, company_id)


def clear_tenant(db: Session) -> None:
    """Reset the session variable (used between tenant switches in a long session)."""
    db.execute(text("SELECT set_config('app.current_company_id', '', false)"))


def require_tenant_company_id(request) -> UUID:
    """Dependency-extracted current company id.

    In a real app this comes from your session/JWT. For the scaffold it is
    passed via the X-Company-Id header (development) — replace with real auth.
    """
    raw = request.headers.get("X-Company-Id")
    if not raw:
        raise PermissionError("missing tenant context")
    return UUID(raw)


class _IteratorCtx:
    def __init__(self, ctx: TenantContext):
        self.ctx = ctx

    def __enter__(self):
        return self.ctx.__enter__()

    def __exit__(self, *exc):
        self.ctx.__exit__(*exc)


def iter_tenant(db: Session, company_id: UUID | str) -> Iterator[TenantContext]:
    """Generator form for use as a FastAPI-like context. (Helper.)"""
    ctx = TenantContext(db, company_id)
    with _IteratorCtx(ctx):  # type: ignore[arg-type]
        yield ctx
