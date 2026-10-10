"""Public aggregate analytics; explicit analytics consent is required."""
from fastapi import APIRouter, Request, Response

from app.schemas.marketing_events import MarketingEventCreate
from app.services import marketing_events

router = APIRouter()


@router.post("/public/marketing-events", status_code=204, responses={429: {}, 503: {}})
def create_marketing_event(body: MarketingEventCreate, request: Request) -> Response:
    marketing_events.count_event(request, body.event)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
