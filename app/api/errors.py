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

from app.services.crud import Conflict, NotFound, ValidationFailed
from app.services.jobs import InvalidTechnician
from app.services.state_machines import IllegalTransition

#: Checked in order, so a subclass must precede its base.
_HTTP_STATUS: tuple[tuple[type[Exception], int], ...] = (
    (NotFound, status.HTTP_404_NOT_FOUND),
    (ValidationFailed, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (InvalidTechnician, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (IllegalTransition, status.HTTP_409_CONFLICT),
    (Conflict, status.HTTP_409_CONFLICT),
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
