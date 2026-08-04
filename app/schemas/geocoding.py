from pydantic import BaseModel


class GeocodeBackfillResponse(BaseModel):
    """Returned by `POST /admin/geocode-backfill`."""

    customers_updated: int
    users_updated: int
