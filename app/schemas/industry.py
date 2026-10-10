"""Server-allowlisted public industry and product classifications."""
from enum import StrEnum


class Industry(StrEnum):
    MARINAS = "marinas"
    MARINE_TOWING = "marine-towing"
    COMMERCIAL_FISHING = "commercial-fishing"
    RECREATIONAL_FISHING = "recreational-fishing"
    MARINE_SERVICE = "marine-service"
    CHARTERS = "charters"
    BOAT_OWNERS = "boat-owners"
    DEALERS = "dealers"
    SUPPLIERS = "suppliers"
    SURVEYORS = "surveyors"
    COMMERCIAL_FLEETS = "commercial-fleets"
    OTHER = "other"


class ProductInterest(StrEnum):
    OPERATIONS = "operations"
    AI = "ai"
    PARTNERSHIP = "partnership"
