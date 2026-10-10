"""Public anonymous demo, explicitly unavailable until a real engine exists."""
from fastapi import APIRouter, HTTPException, Request, Response

from app.core.config import settings
from app.schemas.ai_demo import (
    AIDemoChatRequest,
    AIDemoChatResponse,
    AIDemoSession,
    AIDemoStatus,
)
from app.services import ai_demo

router = APIRouter(prefix="/public/ai-demo")


@router.get("/status", response_model=AIDemoStatus)
def demo_status() -> AIDemoStatus:
    return AIDemoStatus(
        available=False,
        message=ai_demo.UNAVAILABLE_MESSAGE,
        message_limit=settings.ai_demo_message_limit,
        max_message_chars=settings.ai_demo_max_message_chars,
    )


@router.post("/session", response_model=AIDemoSession, responses={429: {}, 503: {}})
def demo_session(request: Request, response: Response) -> AIDemoSession:
    response.headers["Cache-Control"] = "no-store"
    return AIDemoSession(
        session_token=ai_demo.mint_session(request),
        expires_in=settings.ai_demo_session_ttl_seconds,
    )


@router.post(
    "/chat", response_model=AIDemoChatResponse, responses={401: {}, 429: {}, 503: {}}
)
def demo_chat(body: AIDemoChatRequest, request: Request) -> AIDemoChatResponse:
    ai_demo.enforce_chat_limits(request, body.session_token)
    raise HTTPException(503, ai_demo.UNAVAILABLE_MESSAGE)
