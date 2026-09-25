import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)):
    """Readiness: 200 only when the database answers.

    Returns 503 (not 200) when not ready so load balancers and container
    orchestrators actually stop routing traffic, and never echoes the
    driver exception to the caller — connection errors can contain host
    names and role names. The detail goes to the server log instead.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        logger.exception("readyz.database_unavailable")
        return JSONResponse(status_code=503, content={"status": "not_ready", "db": "unavailable"})
    return {"status": "ready", "db": "ok"}
