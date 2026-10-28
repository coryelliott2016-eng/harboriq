"""Audit-log read schemas (v0.2.1)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_user_id: uuid.UUID | None
    #: Resolved at read time; `None` for system/webhook actors or deleted users.
    actor_email: str | None
    actor_ip: str | None
    #: `"<resource>.<past_tense_verb>"`, e.g. `invoice.voided`, `user.role_changed`.
    action: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    metadata: dict[str, Any]
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogEntryOut]
    #: Pass as `before_id` to fetch the next (older) page; `None` at the end.
    next_before_id: int | None
