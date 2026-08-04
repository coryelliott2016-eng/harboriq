"""Dispatch-engine request/response schemas.

`total`/breakdown values come over the wire as JSON strings, matching how
every other Decimal field in this codebase is serialized (Pydantic's default
Decimal encoding) — see `app/schemas/jobs.py`'s comment on the same pattern.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DispatchScoreOut(BaseModel):
    """An explainable score: the total plus every factor's contribution."""

    total: Decimal
    breakdown: dict[str, Decimal]


class DispatchCandidateOut(BaseModel):
    """One technician's ranked score for a specific job."""

    model_config = ConfigDict(from_attributes=True)

    technician_id: uuid.UUID
    technician_name: str
    score: DispatchScoreOut


class JobDispatchScoreOut(BaseModel):
    """The job's own cached technician-independent score."""

    job_id: uuid.UUID
    dispatch_score: Decimal | None
    dispatch_score_breakdown: dict[str, Decimal] | None
    dispatch_scored_at: datetime | None
