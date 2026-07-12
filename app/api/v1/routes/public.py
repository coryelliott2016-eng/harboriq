
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_service_db
from app.schemas.public import ApproveEstimateRequest, ApproveEstimateResponse
from app.services.public_tokens import (
    InvalidToken,
    approve_estimate_with_token,
)
from app.services.state_machines import IllegalTransition

router = APIRouter()


@router.post(
    "/public/estimate/{public_token}/approve",
    response_model=ApproveEstimateResponse,
)
def approve_estimate(
    public_token: str,
    request: Request,
    body: ApproveEstimateRequest,
    db: Session = Depends(get_service_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Public, token-authenticated estimate approval (electronic-signature).

    Uses the SERVICE db (BYPASSRLS) only for the initial global token lookup;
    the actual approval runs inside tenant_context so RLS applies. The whole
    flow is one transaction — a failed transition does not burn the token.
    """
    client_ip = request.client.host if request.client else "0.0.0.0"
    try:
        result = approve_estimate_with_token(
            db,
            public_token,
            ip=client_ip,
            user_agent=user_agent or "",
            estimate_pdf_version=body.estimate_pdf_version,
        )
    except InvalidToken:
        # 404 (not 401) to avoid leaking token existence.
        raise HTTPException(status_code=404)
    except IllegalTransition as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ApproveEstimateResponse(**result)
