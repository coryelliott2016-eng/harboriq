"""Tenant audit trail: append-only rows in `audit_log`.

`audit_log` is created in migration 0001 as an append-only table (UPDATE and
DELETE are rewritten to no-ops by rules) with `FORCE ROW LEVEL SECURITY`, so a
tenant can only ever read or write its own rows. Before v0.2.1 the auth and
estimate services each carried a private `_audit()` helper and money events
(invoice send/void/refund) and role changes were not recorded at all. This
module is the single shared writer and the read path behind
`GET /api/v1/audit-log`.

Conventions
-----------
* `action` is `"<resource>.<past_tense_verb>"`, e.g. `invoice.voided`.
* Callers hold `tenant_context` and own the transaction: `record()` never
  commits, so an audit row and the business change it describes land (or roll
  back) together.
* `metadata` is small, structured, and never contains secrets or card data.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


def record(
    db: Session,
    company_id: uuid.UUID,
    action: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_ip: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one audit row inside the caller's open tenant transaction."""
    db.execute(
        text(
            """
            INSERT INTO audit_log
                (company_id, actor_user_id, actor_ip, action,
                 resource_type, resource_id, metadata)
            VALUES (:cid, :actor, CAST(:ip AS inet), :action,
                    :rt, :rid, CAST(:meta AS jsonb))
            """
        ),
        {
            "cid": company_id,
            "actor": actor_user_id,
            "ip": actor_ip,
            "action": action,
            "rt": resource_type,
            "rid": resource_id,
            "meta": json.dumps(metadata or {}, default=str),
        },
    )


def list_entries(
    db: Session,
    *,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    before_id: int | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[Row]:
    """Newest-first page of the caller's tenant audit trail.

    Keyset-paginated on the BIGSERIAL id (`before_id`) so a busy tenant can
    page back without offset drift. `action` matches exactly or, when it ends
    with `.`, as a prefix (`invoice.` returns every invoice event). RLS scopes
    the rows to the tenant in `tenant_context`; no `company_id` filter is
    needed or trusted here.
    """
    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if action:
        if action.endswith("."):
            clauses.append("action LIKE :action_prefix")
            params["action_prefix"] = f"{action}%"
        else:
            clauses.append("action = :action")
            params["action"] = action
    if resource_type:
        clauses.append("resource_type = :resource_type")
        params["resource_type"] = resource_type
    if resource_id is not None:
        clauses.append("resource_id = :resource_id")
        params["resource_id"] = resource_id
    if actor_user_id is not None:
        clauses.append("actor_user_id = :actor_user_id")
        params["actor_user_id"] = actor_user_id
    if before_id is not None:
        clauses.append("id < :before_id")
        params["before_id"] = before_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return list(
        db.execute(
            text(
                f"""
                SELECT a.id, a.actor_user_id, u.email AS actor_email,
                       host(a.actor_ip) AS actor_ip, a.action,
                       a.resource_type, a.resource_id, a.metadata, a.created_at
                  FROM audit_log a
                  LEFT JOIN users u ON u.id = a.actor_user_id
                  {where}
                 ORDER BY a.id DESC
                 LIMIT :limit
                """
            ),
            params,
        ).all()
    )
