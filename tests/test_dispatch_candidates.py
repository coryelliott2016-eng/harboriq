"""Integration tests for the dispatch-candidates endpoint and the
technician-independent score recompute endpoint.

Covers ranking behaviour end-to-end (through the real API + DB), the
`require_operations` role gate (403 for a technician), and tenant isolation
(company B cannot see or act on company A's job).
"""
from __future__ import annotations

from sqlalchemy import text

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _set_skills(service_db, user_id, skills):
    service_db.execute(
        text("UPDATE users SET skills = :skills WHERE id = :id"),
        {"skills": skills, "id": user_id},
    )
    service_db.commit()


def _set_customer_coords(service_db, customer_id, lat, lon):
    service_db.execute(
        text("UPDATE customers SET latitude = :lat, longitude = :lon WHERE id = :id"),
        {"lat": lat, "lon": lon, "id": customer_id},
    )
    service_db.commit()


def _set_technician_coords(service_db, user_id, lat, lon):
    service_db.execute(
        text(
            "UPDATE users SET home_latitude = :lat, home_longitude = :lon WHERE id = :id"
        ),
        {"lat": lat, "lon": lon, "id": user_id},
    )
    service_db.commit()


def _set_required_skills(service_db, job_id, skills):
    service_db.execute(
        text("UPDATE jobs SET required_skills = :skills WHERE id = :id"),
        {"skills": skills, "id": job_id},
    )
    service_db.commit()


def test_candidates_are_ranked_best_first_by_skill_fit(client, service_db):
    owner = signup(client)
    good_fit = invite(client, owner, "technician")
    poor_fit = invite(client, owner, "technician")

    customer = make_customer(client, owner)
    job = make_job(client, owner, customer).json()

    _set_required_skills(service_db, job["id"], ["outboard", "electrical"])
    _set_skills(service_db, good_fit["user"]["id"], ["outboard", "electrical"])
    _set_skills(service_db, poor_fit["user"]["id"], ["upholstery"])

    resp = client.get(
        f"/api/v1/jobs/{job['id']}/dispatch/candidates", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    candidates = resp.json()

    ids = [c["technician_id"] for c in candidates]
    assert good_fit["user"]["id"] in ids
    assert poor_fit["user"]["id"] in ids

    by_id = {c["technician_id"]: c for c in candidates}
    assert float(by_id[good_fit["user"]["id"]]["score"]["total"]) > float(
        by_id[poor_fit["user"]["id"]]["score"]["total"]
    )
    # The owner (signup creates one) is also a valid assignable candidate.
    assert owner["user"]["id"] in ids


def test_candidates_are_ranked_by_distance_when_coordinates_are_present(
    client, service_db
):
    owner = signup(client)
    close_tech = invite(client, owner, "technician")
    far_tech = invite(client, owner, "technician")

    customer = make_customer(client, owner)
    job = make_job(client, owner, customer).json()

    # Sarasota, FL.
    _set_customer_coords(service_db, customer, "27.3364", "-82.5307")
    _set_technician_coords(service_db, close_tech["user"]["id"], "27.3400", "-82.5300")
    # Tampa, FL — meaningfully farther away.
    _set_technician_coords(service_db, far_tech["user"]["id"], "27.9506", "-82.4572")

    resp = client.get(
        f"/api/v1/jobs/{job['id']}/dispatch/candidates", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    by_id = {c["technician_id"]: c for c in resp.json()}

    # Decimal fields serialize as strings on the wire (see app/schemas/dispatch.py);
    # compare numerically, not lexicographically.
    assert float(
        by_id[close_tech["user"]["id"]]["score"]["breakdown"]["distance"]
    ) > float(by_id[far_tech["user"]["id"]]["score"]["breakdown"]["distance"])


def test_a_technician_cannot_view_dispatch_candidates(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.get(
        f"/api/v1/jobs/{job['id']}/dispatch/candidates", headers=auth_headers(tech)
    )
    assert resp.status_code == 403


def test_office_staff_can_view_dispatch_candidates(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.get(
        f"/api/v1/jobs/{job['id']}/dispatch/candidates", headers=auth_headers(office)
    )
    assert resp.status_code == 200


def test_candidates_are_tenant_isolated(client):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")

    job_a = make_job(client, owner_a, make_customer(client, owner_a)).json()

    resp = client.get(
        f"/api/v1/jobs/{job_a['id']}/dispatch/candidates", headers=auth_headers(owner_b)
    )
    assert resp.status_code == 404


def test_recompute_persists_the_job_level_score(client):
    owner = signup(client)
    job = make_job(client, owner, make_customer(client, owner), priority="urgent").json()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/dispatch/recompute", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dispatch_score"] is not None
    assert "urgency" in body["dispatch_score_breakdown"]

    refreshed = client.get(
        f"/api/v1/jobs/{job['id']}", headers=auth_headers(owner)
    ).json()
    assert refreshed["dispatch_score"] == body["dispatch_score"]
    assert refreshed["dispatch_scored_at"] is not None


def test_recompute_is_tenant_isolated(client):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")
    job_a = make_job(client, owner_a, make_customer(client, owner_a)).json()

    resp = client.post(
        f"/api/v1/jobs/{job_a['id']}/dispatch/recompute", headers=auth_headers(owner_b)
    )
    assert resp.status_code == 404


def test_recompute_is_403_for_a_technician(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/dispatch/recompute", headers=auth_headers(tech)
    )
    assert resp.status_code == 403
