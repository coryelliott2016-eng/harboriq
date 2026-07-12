"""Database engines and sessions.

Two roles:
  - app engine      : harboriq_app, RLS-enforced (tenant-scoped requests)
  - service engine  : harboriq_service, BYPASSRLS (webhook resolution, token lookup)
"""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

app_engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
AppSession = sessionmaker(bind=app_engine, class_=Session, expire_on_commit=False)

service_engine = create_engine(
    settings.service_database_url, future=True, pool_pre_ping=True
)
ServiceSession = sessionmaker(bind=service_engine, class_=Session, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding an app-role session (RLS applies)."""
    db = AppSession()
    try:
        yield db
    finally:
        db.close()


def get_service_db() -> Iterator[Session]:
    """FastAPI dependency yielding a service-role session (BYPASSRLS)."""
    db = ServiceSession()
    try:
        yield db
    finally:
        db.close()
