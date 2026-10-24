"""Public demo gateway: no database/auth dependency or operational side effects."""
from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.rate_limit import enforce_public_ai_rate_limit
from app.schemas.public_demo import PublicDemoRequest, PublicDemoResponse
from app.services.public_demo import generate_demo

router = APIRouter()


@router.post("/public/demo", response_model=PublicDemoResponse)
def public_demo(body: PublicDemoRequest, request: Request) -> PublicDemoResponse:
    if not settings.public_ai_enabled or not settings.public_ai_api_key.strip():
        raise HTTPException(status_code=503, detail="public AI demo is disabled")
    enforce_public_ai_rate_limit(request)
    return generate_demo(body)
