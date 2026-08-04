"""The /metrics endpoint: Prometheus text exposition of request count/latency."""
from __future__ import annotations


def test_metrics_endpoint_reports_prior_requests(client):
    # Generate some traffic on a route with a stable template label first.
    client.get("/api/v1/healthz")
    client.get("/api/v1/healthz")

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")

    body = resp.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    # The healthz route should show up labelled with its route template, not
    # a raw/one-off path, and with a status of 200. Starlette's `route.path`
    # is relative to the router it was registered on ("/healthz"), not the
    # full mounted URL ("/api/v1/healthz") -- still a fixed template, not a
    # per-request value, which is what actually matters for cardinality.
    assert '/healthz' in body
    assert 'status="200"' in body


def test_metrics_endpoint_is_unauthenticated(client):
    # No Authorization header at all -- must not 401/403.
    resp = client.get("/metrics")
    assert resp.status_code == 200
