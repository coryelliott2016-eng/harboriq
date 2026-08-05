"""Message request/response schemas (Phase 9)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import MessageSenderType
from app.schemas.common import RequiredText


class MessageCreate(BaseModel):
    body: RequiredText = Field(min_length=1, max_length=5000)
    #: Omit for a general (not job-specific) message.
    job_id: uuid.UUID | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    customer_id: uuid.UUID
    job_id: uuid.UUID | None
    sender_type: MessageSenderType
    sender_user_id: uuid.UUID | None
    body: str
    #: 'portal' or 'sms' (migration 0010, Phase 11) — how this message
    #: arrived, not necessarily how a reply to it will go out.
    channel: str
    created_at: datetime
    read_at: datetime | None


class StaffMessageCreate(MessageCreate):
    """Staff reply — targets a specific customer (and optionally a job)."""

    customer_id: uuid.UUID


class InboxMessageOut(MessageOut):
    """A message as it appears in the staff-wide inbox, with a denormalized
    customer label so the UI does not need a second lookup per row."""

    customer_label: str | None = None

    @classmethod
    def from_row(cls, row) -> "InboxMessageOut":
        label = row.company_name or " ".join(
            filter(None, [row.first_name, row.last_name])
        ) or None
        out = cls.model_validate(row)
        out.customer_label = label
        return out
