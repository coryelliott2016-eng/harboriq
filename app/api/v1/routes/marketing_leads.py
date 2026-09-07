"""Public marketing lead capture — GTM / trial signup from harboriq.com.

Unauthenticated POST stores the lead (service role) and emails the platform
owner. Admin list is gated by MARKETING_LEADS_ADMIN_TOKEN, not a tenant JWT.
"""
from __future__ import annotations

import ipaddress
import secrets
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import get_service_db
from app.core.config import settings
from app.core.rate_limit import enforce_marketing_lead_rate_limit
from app.db.session import ServiceSession
from app.schemas.marketing_leads import (
    MarketingLeadCreate,
    MarketingLeadCreateResponse,
    MarketingLeadListResponse,
    MarketingLeadOut,
)
from app.services import marketing_leads as leads_service

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP as a valid inet-parseable string, or None.

    Postgres `inet` rejects non-IP tokens (e.g. Starlette TestClient's
    literal `"testclient"` host), so we validate before returning. Any
    unparseable value collapses to None.
    """
    candidate: str | None = None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        candidate = forwarded.split(",")[0].strip()[:64] or None
    elif request.client is not None:
        candidate = request.client.host

    if not candidate:
        return None
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def _notify_and_mark(lead_id: uuid.UUID, lead_snapshot: dict) -> None:
    """Background task: send email, then stamp notified_at on success."""
    ok = leads_service.notify_new_lead(lead_snapshot)
    if not ok:
        return
    db = ServiceSession()
    try:
        leads_service.mark_notified(db, lead_id)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


@router.post(
    "/public/leads",
    response_model=MarketingLeadCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_marketing_lead(
    body: MarketingLeadCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_service_db),
    user_agent: Annotated[str | None, Header(alias="User-Agent")] = None,
):
    """Public trial / demo signup from the marketing site.

    Honeypot: if `website` is non-empty, return a fake success without storing.
    Soft de-dupe: same email within 24h returns the existing lead without a
    second notification email.
    """
    enforce_marketing_lead_rate_limit(request)

    if body.website.strip():
        # Bot trap — do not reveal detection.
        return MarketingLeadCreateResponse(
            id=uuid.uuid4(),
            duplicate=False,
            message=(
                "Thanks — we've got your request. Our team will follow up "
                "within one business day."
            ),
        )

    existing = leads_service.find_recent_duplicate(db, body.email)
    if existing:
        db.commit()  # no writes, but keep session lifecycle clean
        return MarketingLeadCreateResponse(
            id=existing["id"],
            duplicate=True,
            message=(
                "Thanks — we've already got your request and will follow up soon."
            ),
        )

    lead = leads_service.create_lead(
        db,
        full_name=body.full_name,
        business_name=body.business_name,
        email=body.email,
        team_size=body.team_size,
        source=body.source,
        ip_hint=_client_ip(request),
        user_agent=user_agent,
    )
    db.commit()

    background_tasks.add_task(_notify_and_mark, lead["id"], dict(lead))

    return MarketingLeadCreateResponse(
        id=lead["id"],
        duplicate=False,
        message=(
            "Thanks — we've got your request. Our team will follow up "
            "within one business day."
        ),
    )


@router.get(
    "/public/leads",
    response_model=MarketingLeadListResponse,
)
def list_marketing_leads(
    authorization: Annotated[str | None, Header()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    db: Session = Depends(get_service_db),
):
    """Platform admin list. Requires `Authorization: Bearer <MARKETING_LEADS_ADMIN_TOKEN>`."""
    expected = (settings.marketing_leads_admin_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="marketing leads admin token is not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided = ""
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    rows = leads_service.list_leads(db, limit=limit)
    leads = [MarketingLeadOut.model_validate(r) for r in rows]
    return MarketingLeadListResponse(count=len(leads), leads=leads)
