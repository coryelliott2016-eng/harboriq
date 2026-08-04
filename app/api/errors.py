"""Translation of service-layer domain errors into HTTP responses.

The services raise domain exceptions and know nothing about HTTP; the routes
own the status codes. Keeping the mapping in one place means every endpoint
answers the same way for the same failure, which matters most for `NotFound`:
under RLS, "belongs to another tenant" is indistinguishable from "does not
exist", and both must be a 404 that leaks nothing.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status

from app.services.auth import AccountLocked
from app.services.crud import Conflict, NotFound, ValidationFailed
from app.services.jobs import InvalidTechnician
from app.services.state_machines import IllegalTransition

#: Checked in order, so a subclass must precede its base.
#: 423 Locked (WebDAV, RFC 4918 §11.3 — repurposed here as the generic "this
#: resource is temporarily locked" status) is what an account-lockout error
#: maps to, distinct from 401 (bad credentials) so a client can tell the two
#: apart without the response body revealing anything about remaining
#: attempts or account existence.
_HTTP_STATUS: tuple[tuple[type[Exception], int], ...] = (
    (NotFound, status.HTTP_404_NOT_FOUND),
    (ValidationFailed, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (InvalidTechnician, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (IllegalTransition, status.HTTP_409_CONFLICT),
    (Conflict, status.HTTP_409_CONFLICT),
    (AccountLocked, status.HTTP_423_LOCKED),
)


@contextmanager
def http_errors() -> Iterator[None]:
    """Re-raise domain exceptions as HTTPExceptions with the agreed status."""
    try:
        yield
    except tuple(exc for exc, _ in _HTTP_STATUS) as exc:
        for kind, code in _HTTP_STATUS:
            if isinstance(exc, kind):
                raise HTTPException(code, str(exc)) from exc
        raise  # unreachable: the except clause is built from the same table
