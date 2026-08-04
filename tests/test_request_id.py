"""RequestIDMiddleware: generation, echo, and propagation of an inbound id."""
from __future__ import annotations

import uuid

from app.api.middleware import REQUEST_ID_HEADER


def test_response_carries_a_request_id_header(client):
    resp = client.get("/api/v1/healthz")
    assert resp.status_code == 200
    assert REQUEST_ID_HEADER in resp.headers
    # Must be a real, non-empty value — parseable as a UUID when the server
    # generated it itself (no inbound header was sent on this request).
    assert uuid.UUID(resp.headers[REQUEST_ID_HEADER])


def test_inbound_request_id_is_echoed_back_unchanged(client):
    inbound = "caller-supplied-id-123"
    resp = client.get("/api/v1/healthz", headers={REQUEST_ID_HEADER: inbound})
    assert resp.status_code == 200
    assert resp.headers[REQUEST_ID_HEADER] == inbound


def test_two_requests_without_inbound_header_get_different_ids(client):
    first = client.get("/api/v1/healthz").headers[REQUEST_ID_HEADER]
    second = client.get("/api/v1/healthz").headers[REQUEST_ID_HEADER]
    assert first != second
