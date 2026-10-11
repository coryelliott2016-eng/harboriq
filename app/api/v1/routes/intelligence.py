"""Public demo routes deliberately have no authentication/tenant DB dependency."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.core import demo_limits
from app.core.config import settings
from app.schemas.intelligence import (
    AssistRequest,
    AssistResponse,
    DemoSessionRequest,
    DemoSessionResponse,
)
from app.services import intelligence_demo


def require_enabled():
    if not settings.intelligence_demo_enabled:
        raise HTTPException(404, "The public intelligence demo is disabled.")


router = APIRouter(
    prefix="/public/intelligence", tags=["public", "intelligence"],
    dependencies=[Depends(require_enabled)],
)


@router.post("/sessions", response_model=DemoSessionResponse)
def create_session(body: DemoSessionRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    # Do not trust X-Forwarded-For; only the ASGI peer identity is used.
    if request.client is None:
        raise HTTPException(503, "The public demo is temporarily unavailable.")
    return demo_limits.create_session(request.client.host)


@router.post("/assist", response_model=AssistResponse)
def assist(
    body: AssistRequest, response: Response,
    session_token: Annotated[str, Header(alias="X-Demo-Session", min_length=43, max_length=43)],
):
    response.headers["Cache-Control"] = "no-store"
    return intelligence_demo.assist(body, session_token)
