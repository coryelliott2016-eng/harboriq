"""Field-app request/response schemas (Phase 12): job attachments (photos +
digital signatures) and time-clock entries.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import JobAttachmentKind
from app.schemas.common import OptionalText

#: Generous enough for a phone-camera photo re-encoded at reasonable quality
#: (a signature trace is a few KB) while still bounding the base64 MVP
#: fallback documented in migration 0011's SQL comment. ~6.7 MB of raw bytes
#: once base64's ~33% overhead is accounted for.
MAX_ATTACHMENT_BASE64_CHARS = 9_000_000


class JobAttachmentCreate(BaseModel):
    kind: JobAttachmentKind
    #: Base64-encoded bytes (no `data:` URL prefix — strip that client-side).
    data: str = Field(min_length=1, max_length=MAX_ATTACHMENT_BASE64_CHARS)
    content_type: str = Field(default="image/jpeg", max_length=100)
    #: Client-generated key from the offline-sync queue. Replaying the same
    #: queued action (e.g. after a dropped response) with the same key is a
    #: no-op that returns the original row rather than creating a duplicate.
    idempotency_key: OptionalText = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _strip_data_url_prefix(self) -> "JobAttachmentCreate":
        # Defensive: browsers' FileReader.readAsDataURL yields
        # "data:image/jpeg;base64,...."; accept it but store only the payload.
        if self.data.startswith("data:") and "," in self.data:
            self.data = self.data.split(",", 1)[1]
        return self


class JobAttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    kind: JobAttachmentKind
    content_type: str
    uploaded_by: uuid.UUID
    created_at: datetime
    #: The base64 payload is included on read too — there is no separate
    #: object-storage URL to redirect to yet (see migration 0011's comment).
    data: str | None = None


class JobTimeEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    technician_id: uuid.UUID
    clocked_in_at: datetime
    clocked_out_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ClockActionRequest(BaseModel):
    #: Same idempotency story as attachments — the offline queue may replay
    #: a clock-in/out after a dropped response.
    idempotency_key: OptionalText = Field(default=None, max_length=200)
