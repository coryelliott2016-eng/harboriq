"""Tenant-facing Marine Signals feed, source setup, and editorial workflow."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_company_id,
    get_current_user,
    get_db,
    require_admin,
    require_operations,
)
from app.schemas.marine_signals import (
    MarineSignalCreate,
    MarineSignalFeedbackInput,
    MarineSignalMetrics,
    MarineSignalOut,
    MarineSignalProfileInput,
    MarineSignalProfileOut,
    MarineSignalReview,
    MarineSignalSourceCreate,
    MarineSignalSourceOut,
    SignalCategory,
)
from app.services import outbox
from app.services.outbox_dispatch import dispatch_outbox_soon
from app.services import marine_signals as service

router = APIRouter(
    prefix="/marine-signals",
    tags=["marine-signals"],
    dependencies=[Depends(require_operations)],
)


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/sources", response_model=list[MarineSignalSourceOut])
def list_sources(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.list_sources(db, company_id)


@router.post(
    "/sources",
    response_model=MarineSignalSourceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_source(
    body: MarineSignalSourceCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    values = body.model_dump(exclude={"terms_confirmed"})
    for field in ("source_url", "feed_url", "terms_url"):
        values[field] = str(values[field])
    result = service.create_source(db, company_id, values)
    db.commit()
    return result


@router.patch(
    "/sources/{source_id}/enabled",
    response_model=MarineSignalSourceOut,
    dependencies=[Depends(require_admin)],
)
def set_source_enabled(
    source_id: uuid.UUID,
    enabled: bool,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    try:
        result = service.set_source_enabled(db, company_id, source_id, enabled)
    except LookupError as exc:
        raise _not_found(exc) from exc
    db.commit()
    return result


@router.get("/signals", response_model=list[MarineSignalOut])
def list_signals(
    include_review: bool = False,
    category: SignalCategory | None = Query(default=None),
    feedback: str | None = Query(
        default=None, pattern="^(saved|dismissed|flagged|useful|acted)$"
    ),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user=Depends(get_current_user),
):
    if include_review and user.role not in {"owner", "admin", "office"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operations role required")
    signals = service.list_signals(
        db,
        company_id,
        user.id,
        include_review=include_review,
        category=category,
        feedback=feedback,
    )
    profile = service.get_profile(db, company_id)
    interests = set(profile["interests"])
    area = profile["service_area"].strip().casefold()
    relevant = []
    for signal in signals:
        if signal["status"] == "published":
            if (
                signal["priority"] != "urgent"
                and interests
                and signal["category"] not in interests
            ):
                continue
            geography = (signal["geography"] or "").casefold()
            if (
                signal["priority"] != "urgent"
                and area
                and geography
                and area not in geography
                and geography not in area
            ):
                continue
        relevant.append(signal)
    return relevant


@router.post("/signals", response_model=MarineSignalOut, status_code=status.HTTP_201_CREATED)
def create_signal(
    body: MarineSignalCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    data = body.model_dump(exclude={"source_id"})
    data["source_id"] = body.source_id
    data["citation_url"] = str(body.citation_url)
    try:
        result = service.create_signal(db, company_id, data)
    except LookupError as exc:
        raise _not_found(exc) from exc
    db.commit()
    return result


@router.post(
    "/signals/{signal_id}/review",
    response_model=MarineSignalOut,
    dependencies=[Depends(require_admin)],
)
def review_signal(
    signal_id: uuid.UUID,
    body: MarineSignalReview,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user=Depends(get_current_user),
):
    try:
        result = service.review_signal(db, company_id, signal_id, user.id, body.model_dump())
    except LookupError as exc:
        raise _not_found(exc) from exc
    profile = service.get_profile(db, company_id) if result["priority"] == "urgent" else None
    notify = bool(profile and profile["digest_enabled"] and profile["digest_email"])
    if notify:
        outbox.enqueue(
            db,
            company_id,
            "marine_signal.urgent_alert",
            {
                "to": profile["digest_email"],
                "title": result["title"],
                "summary": result["summary"],
                "why_it_matters": result["why_it_matters"],
                "suggested_action": result["suggested_action"],
                "uncertainty": result["uncertainty"],
                "citation_url": result["citation_url"],
            },
        )
    db.commit()
    if notify:
        dispatch_outbox_soon(background_tasks)
    return result


@router.patch(
    "/signals/{signal_id}/status",
    response_model=MarineSignalOut,
    dependencies=[Depends(require_admin)],
)
def set_signal_status(
    signal_id: uuid.UUID,
    target: Literal["stale", "superseded"] = Query(alias="status"),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    try:
        result = service.set_signal_status(db, company_id, signal_id, target)
    except LookupError as exc:
        raise _not_found(exc) from exc
    db.commit()
    return result


@router.put("/signals/{signal_id}/feedback")
def feedback_signal(
    signal_id: uuid.UUID,
    body: MarineSignalFeedbackInput,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user=Depends(get_current_user),
):
    try:
        result = service.add_feedback(
            db, company_id, signal_id, user.id, body.feedback, body.note
        )
    except LookupError as exc:
        raise _not_found(exc) from exc
    db.commit()
    return result


@router.get("/profile", response_model=MarineSignalProfileOut)
def get_profile(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.get_profile(db, company_id)


@router.put(
    "/profile",
    response_model=MarineSignalProfileOut,
    dependencies=[Depends(require_admin)],
)
def save_profile(
    body: MarineSignalProfileInput,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    result = service.save_profile(
        db, company_id, body.model_dump(mode="json")
    )
    db.commit()
    return result


@router.get("/metrics", response_model=MarineSignalMetrics)
def get_metrics(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.metrics(db, company_id)
