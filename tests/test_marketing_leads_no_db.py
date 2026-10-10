"""Lead acknowledgement and honeypot behavior without a database."""
import uuid
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, Request

from app.api.v1.routes import marketing_leads
from app.schemas.marketing_leads import MarketingLeadCreate

pytestmark = pytest.mark.no_db


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """No external rate-limit state is used in these direct boundary tests."""


@pytest.mark.parametrize("honeypot,duplicate", [(True, False), (False, True), (False, False)])
def test_honeypot_or_honest_saved_acknowledgement(monkeypatch, honeypot, duplicate):
    from fastapi import HTTPException

    row = {"id": uuid.uuid4()}
    monkeypatch.setattr(marketing_leads, "enforce_marketing_lead_rate_limit", lambda _: None)
    find = Mock(return_value=row if duplicate else None)
    create = Mock(return_value=row)
    monkeypatch.setattr(marketing_leads.leads_service, "find_recent_duplicate", find)
    monkeypatch.setattr(marketing_leads.leads_service, "create_lead", create)
    body = MarketingLeadCreate(
        full_name="Demo Visitor", business_name="Marine Business",
        email="demo@example.com", team_size="solo",
        website="spam.example" if honeypot else "",
    )
    db, background = Mock(), BackgroundTasks()
    request = Request({"type": "http", "client": ("198.51.100.1", 1234), "headers": []})
    if honeypot:
        with pytest.raises(HTTPException) as error:
            marketing_leads.create_marketing_lead(body, request, background, db, None)
        assert error.value.status_code == 400
        assert error.value.detail == "Unable to accept this request."
        find.assert_not_called()
        create.assert_not_called()
        db.commit.assert_not_called()
        assert background.tasks == []
    else:
        result = marketing_leads.create_marketing_lead(body, request, background, db, None)
        assert result.id == row["id"]
        assert result.duplicate is duplicate
        assert "saved" in result.message
        assert "not guaranteed" in result.message
        assert "business day" not in result.message
        db.commit.assert_called_once()


def test_redis_outage_rejects_lead_before_storage_or_notification(monkeypatch):
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError

    from app.core import rate_limit

    backend = Mock()
    backend.eval.side_effect = ConnectionError("Redis is unavailable")
    monkeypatch.setattr(rate_limit, "get_redis", lambda: backend)
    find, create = Mock(), Mock()
    monkeypatch.setattr(marketing_leads.leads_service, "find_recent_duplicate", find)
    monkeypatch.setattr(marketing_leads.leads_service, "create_lead", create)
    body = MarketingLeadCreate(
        full_name="Demo Visitor", business_name="Marine Business",
        email="demo@example.com", team_size="solo",
    )
    db, background = Mock(), BackgroundTasks()
    request = Request({"type": "http", "client": ("198.51.100.1", 1234), "headers": []})
    with pytest.raises(HTTPException) as error:
        marketing_leads.create_marketing_lead(body, request, background, db, None)
    assert error.value.status_code == 503
    find.assert_not_called()
    create.assert_not_called()
    db.commit.assert_not_called()
    assert background.tasks == []


@pytest.mark.parametrize("limiter_name", ["_login_limiter", "_password_reset_limiter"])
def test_auth_limiters_still_fail_open_on_redis_outage(monkeypatch, limiter_name):
    from redis.exceptions import ConnectionError

    from app.core import rate_limit

    backend = Mock()
    backend.eval.side_effect = ConnectionError("Redis is unavailable")
    monkeypatch.setattr(rate_limit, "get_redis", lambda: backend)
    assert getattr(rate_limit, limiter_name).hit("198.51.100.1") == (True, 0)


def test_marketing_quota_still_returns_429_with_retry_after(monkeypatch):
    from fastapi import HTTPException

    from app.core import rate_limit

    backend = Mock()
    backend.eval.return_value = (rate_limit._marketing_lead_limiter.limit + 1, 123)
    monkeypatch.setattr(rate_limit, "get_redis", lambda: backend)
    request = Request({"type": "http", "client": ("198.51.100.1", 1234), "headers": []})
    with pytest.raises(HTTPException) as error:
        rate_limit.enforce_marketing_lead_rate_limit(request)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "123"
