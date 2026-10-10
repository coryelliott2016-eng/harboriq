import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.industry import Industry
from app.schemas.marketing_leads import MarketingLeadCreate

pytestmark = pytest.mark.no_db

BASE = {"full_name": "Test", "business_name": "Marine", "email": "test@example.com"}


def test_legacy_defaults_do_not_imply_marketing_consent():
    lead = MarketingLeadCreate(**BASE)
    assert lead.industry == "other"
    assert lead.product_interest == "operations"
    assert lead.business_need == ""
    assert lead.contact_requested is True
    assert lead.email_marketing_opt_in is False


@pytest.mark.parametrize("industry", list(Industry))
def test_shared_industry_allowlist(industry):
    assert MarketingLeadCreate(**BASE, industry=industry).industry == industry


def test_frontend_taxonomy_matches_server_allowlist():
    path = Path(__file__).resolve().parents[1] / "frontend/src/lib/industries.json"
    industries = json.loads(path.read_text())
    ids = [industry["id"] for industry in industries]
    assert len(ids) == len(set(ids))
    assert set(ids) == {industry.value for industry in Industry}


@pytest.mark.parametrize("extra", [
    {"industry": "Marinas"}, {"industry": "invalid"}, {"product_interest": "referrals"},
    {"business_need": "x" * 2001}, {"email_marketing_opt_in": "true"},
    {"contact_requested": 1},
])
def test_invalid_classification_consent_or_bounds(extra):
    with pytest.raises(ValidationError):
        MarketingLeadCreate(**BASE, **extra)
