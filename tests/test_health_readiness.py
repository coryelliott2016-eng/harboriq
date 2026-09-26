"""Readiness must fail closed (503) and must not leak driver errors."""
from __future__ import annotations

from sqlalchemy.exc import OperationalError

from app.api.deps import get_db
from app.main import app


def test_readyz_ok_when_database_answers(client):
    resp = client.get("/api/v1/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "db": "ok"}


def test_readyz_returns_503_without_leaking_error_details(client):
    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise OperationalError(
                "SELECT 1", {}, Exception("could not connect to db-host-secret:5432 as harboriq_app")
            )

    def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    try:
        resp = client.get("/api/v1/readyz")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 503
    assert resp.json() == {"status": "not_ready", "db": "unavailable"}
    assert "db-host-secret" not in resp.text
    assert "harboriq_app" not in resp.text
