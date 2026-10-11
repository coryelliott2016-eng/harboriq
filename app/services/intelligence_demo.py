"""Deterministic source-based interpretation, not an LLM or diagnostic engine."""
from fastapi import HTTPException

from app.core import demo_limits
from app.schemas.intelligence import AssistRequest, AssistResponse
from app.services import noaa

WARNINGS = [
    "Human verification is required before any operational decision.",
    "Not for emergencies, navigation, vessel clearance, or equipment diagnostics.",
    "NOAA observations may be preliminary and subject to revision.",
    "NOAA does not endorse HarborIQ. This is a deterministic summary, not AI diagnostics.",
]


def assist(request: AssistRequest, token: str) -> AssistResponse:
    if request.product != "water_level":
        raise HTTPException(
            422, "Currents are not available for these water-level stations. Select water_level.",
        )
    remaining = demo_limits.reserve_call(token)
    try:
        observation = noaa.fetch_water_level(request.station)
    except noaa.NOAAUnavailable as exc:
        raise HTTPException(
            502, "Fresh NOAA observations are unavailable. No substitute data has been generated.",
        ) from exc
    latest = observation.measurements[-1]
    context = (
        "Marine service planning requires a qualified technician's independent assessment."
        if request.sector == "service"
        else "Marina planning requires independently verified local conditions and clearances."
    )
    return AssistResponse(
        sector=request.sector,
        summary=(
            f"NOAA reports a water level of {latest.value} feet relative to MLLW at "
            f"{noaa.STATIONS[request.station]}, observed {latest.time} (UTC). {context} "
            "One observation does not establish a trend or safe operating conditions."
        ),
        source_url=observation.source_url,
        source_name="NOAA CO-OPS Tides and Currents",
        retrieved_at=observation.retrieved_at,
        observed_at=observation.observed_at,
        station=request.station,
        product=request.product,
        measurements=observation.measurements,
        warnings=WARNINGS.copy(),
        requests_remaining=remaining,
    )
