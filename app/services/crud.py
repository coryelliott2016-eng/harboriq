"""Shared helpers for the tenant-scoped CRUD services.

Every service in this package follows the same discipline as `services/auth.py`:
all work happens on the APP role inside `tenant_context`, so RLS — not a WHERE
clause the developer must remember — is what keeps tenants apart. The queries
still carry `company_id` where it helps the planner use a composite index, but
correctness does not depend on it.
"""
from __future__ import annotations

from typing import Any


class NotFound(Exception):
    """The requested row does not exist in the caller's tenant.

    RLS makes "belongs to another tenant" and "does not exist" indistinguishable
    at the query level, which is exactly the desired API behaviour: both are 404
    and neither confirms that an id exists elsewhere.
    """


class Conflict(Exception):
    """The write violates a uniqueness rule (e.g. a duplicate hull id)."""


class ValidationFailed(Exception):
    """The write violates a domain rule the database enforces as a CHECK."""


def like_term(search: str) -> str:
    """Wrap a user's search string as an ILIKE pattern, escaping its wildcards.

    Somebody typing `%` is looking for a percent sign, not asking for every row,
    and a hull id containing `_` should not match any character. Postgres treats
    backslash as the default LIKE escape character, so the backslash itself has
    to be doubled first.
    """
    escaped = (
        search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def assignments(changes: dict[str, Any], allowed: frozenset[str]) -> str:
    """Render `col = :col` pairs for a partial UPDATE.

    Keys originate from pydantic model fields, but they are still checked
    against an explicit allow-list: column names cannot be bound as parameters,
    so this is the only thing standing between a future refactor and SQL
    injection. An unexpected key is a programming error, not user input.
    """
    unknown = sorted(set(changes) - allowed)
    if unknown:
        raise ValueError(f"not updatable columns: {unknown}")
    return ", ".join(f"{column} = :{column}" for column in changes)
