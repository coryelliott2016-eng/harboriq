"""Shared field types for the request schemas.

Web forms submit empty strings, not nulls. Storing `''` alongside NULL would
give two representations of "not provided" and quietly defeat both the
`ck_customers_has_a_name` CHECK and the partial indexes that skip NULLs, so
blank input is normalised to None at the edge.
"""
from typing import Annotated

from pydantic import BeforeValidator


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


#: An optional free-text field: trimmed, and blank becomes None.
OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]

#: A required free-text field that may not be blank or whitespace-only.
RequiredText = Annotated[str, BeforeValidator(_blank_to_none)]
