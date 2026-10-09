"""Deterministic marine diagnostic reasoning foundation.

This module intentionally avoids LLM-only outputs: it combines symptom parsing
with hard validation rules over technician-provided measurements so every
recommendation is tied to explicit evidence.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankedHypothesis:
    code: str
    title: str
    score: float
    rationale: list[str]
    recommended_tests: list[str]
    required_tools: list[str]
    safety_precautions: list[str]
    supporting_references: list[str]
    suggested_repair_paths: list[str]
    post_repair_verification: list[str]


@dataclass(frozen=True)
class DiagnosticAssessment:
    reported_symptoms: list[str]
    available_measurements: dict[str, float]
    ranked_hypotheses: list[RankedHypothesis]
    missing_measurements: list[str]
    deterministic_validations: list[str]
    uncertainty_notes: list[str]
    confidence: float


@dataclass(frozen=True)
class _HypothesisTemplate:
    title: str
    recommended_tests: list[str]
    required_tools: list[str]
    safety_precautions: list[str]
    supporting_references: list[str]
    suggested_repair_paths: list[str]
    post_repair_verification: list[str]
    required_measurements: list[str]


_HYPOTHESES: dict[str, _HypothesisTemplate] = {
    "battery_connection_fault": _HypothesisTemplate(
        title="Battery state-of-charge or high-resistance connection fault",
        recommended_tests=[
            "Measure battery open-circuit voltage after resting.",
            "Perform loaded voltage-drop test across positive and negative paths.",
        ],
        required_tools=["Digital multimeter", "Battery load tester", "Insulated hand tools"],
        safety_precautions=["Isolate ignition before wiring work", "Ventilate battery compartment"],
        supporting_references=["ABYC E-11 DC electrical systems guidelines"],
        suggested_repair_paths=["Clean/torque terminals", "Charge or replace failing battery"],
        post_repair_verification=[
            "Engine cranks at expected speed.",
            "Voltage drop under crank is within manufacturer limits.",
        ],
        required_measurements=["battery_voltage_rest_v", "battery_voltage_running_v"],
    ),
    "charging_system_fault": _HypothesisTemplate(
        title="Alternator/regulator charging system underperformance",
        recommended_tests=[
            "Measure charging voltage at idle and cruise RPM.",
            "Inspect belt/slip and regulator wiring continuity.",
        ],
        required_tools=["Digital multimeter", "Clamp ammeter"],
        safety_precautions=["Keep clear of moving belts and pulleys"],
        supporting_references=["ABYC E-11 charging circuit checks"],
        suggested_repair_paths=[
            "Repair wiring faults and grounds",
            "Replace failing regulator/alternator per OEM procedure",
        ],
        post_repair_verification=[
            "Running voltage stabilizes in expected charging range.",
            "Battery recovers after normal duty cycle.",
        ],
        required_measurements=["battery_voltage_running_v"],
    ),
    "cooling_system_restriction": _HypothesisTemplate(
        title="Cooling flow restriction or impeller degradation",
        recommended_tests=[
            "Verify raw-water discharge flow and tell-tale stream consistency.",
            "Check impeller, thermostat, and intake obstructions.",
        ],
        required_tools=["IR thermometer", "Cooling-system pressure tools"],
        safety_precautions=[
            "Shut down immediately on critical overheat indications.",
            "Avoid opening hot cooling systems under pressure.",
        ],
        supporting_references=["OEM cooling-system diagnostic sequence"],
        suggested_repair_paths=[
            "Replace impeller and damaged cooling components",
            "Clear intake/exchanger restriction",
        ],
        post_repair_verification=[
            "Coolant/water temperature remains stable through sea-trial load.",
            "No overheat alarm after repair.",
        ],
        required_measurements=["coolant_temp_f"],
    ),
    "fuel_delivery_restriction": _HypothesisTemplate(
        title="Fuel delivery restriction, contamination, or pressure loss",
        recommended_tests=[
            "Measure rail/fuel pressure against OEM spec under load.",
            "Inspect filters, anti-siphon valve, and fuel-water separator.",
        ],
        required_tools=["Fuel pressure gauge", "Clear sample jar"],
        safety_precautions=["Eliminate ignition sources before fuel-system service"],
        supporting_references=["OEM fuel-system pressure chart"],
        suggested_repair_paths=[
            "Replace blocked filters",
            "Correct pump/regulator faults",
            "Drain contaminated fuel where permitted",
        ],
        post_repair_verification=[
            "Pressure remains in range at idle and acceleration.",
            "No hesitation or stall under commanded load.",
        ],
        required_measurements=["fuel_pressure_psi"],
    ),
    "ignition_control_fault": _HypothesisTemplate(
        title="Ignition/sensor control fault causing intermittent misfire or stall",
        recommended_tests=[
            "Scan for active and pending fault codes.",
            "Check spark quality and coil primary/secondary integrity.",
        ],
        required_tools=["Diagnostic scan tool", "Ignition spark tester"],
        safety_precautions=["Disable fuel and ignition before spark component removal"],
        supporting_references=["OEM ignition and ECU fault tree"],
        suggested_repair_paths=[
            "Repair wiring/connector faults",
            "Replace failed coil/sensor components",
        ],
        post_repair_verification=[
            "No recurring ignition DTCs after duty-cycle test.",
            "Engine accelerates without misfire events.",
        ],
        required_measurements=[],
    ),
}


def _score_symptoms(symptoms: list[str]) -> tuple[dict[str, float], list[str]]:
    normalized = [item.strip() for item in symptoms if item and item.strip()]
    lowered = [item.lower() for item in normalized]
    scores = {code: 0.0 for code in _HYPOTHESES}

    for text in lowered:
        if "won't start" in text or "no start" in text or "hard start" in text:
            scores["battery_connection_fault"] += 0.25
            scores["fuel_delivery_restriction"] += 0.12
            scores["ignition_control_fault"] += 0.12
        if "overheat" in text or "hot alarm" in text or "high temp" in text:
            scores["cooling_system_restriction"] += 0.45
        if "stall" in text or "surge" in text or "cuts out" in text:
            scores["fuel_delivery_restriction"] += 0.24
            scores["ignition_control_fault"] += 0.18
        if "low voltage" in text or "battery light" in text or "battery drains" in text:
            scores["battery_connection_fault"] += 0.18
            scores["charging_system_fault"] += 0.32
    return scores, normalized


def _apply_measurement_rules(
    scores: dict[str, float], measurements: dict[str, float]
) -> list[str]:
    validations: list[str] = []

    rest_v = measurements.get("battery_voltage_rest_v")
    if rest_v is not None:
        if rest_v < 12.2:
            scores["battery_connection_fault"] += 0.25
            validations.append("battery_voltage_rest_v below nominal threshold (<12.2V).")
        else:
            validations.append("battery_voltage_rest_v within nominal resting range.")

    running_v = measurements.get("battery_voltage_running_v")
    if running_v is not None:
        if running_v < 13.2:
            scores["charging_system_fault"] += 0.45
            scores["battery_connection_fault"] += 0.1
            validations.append("battery_voltage_running_v below charging threshold (<13.2V).")
        elif running_v > 14.9:
            scores["charging_system_fault"] += 0.2
            validations.append("battery_voltage_running_v above expected range (>14.9V).")
        else:
            validations.append("battery_voltage_running_v in expected charging range.")

    coolant_temp = measurements.get("coolant_temp_f")
    if coolant_temp is not None:
        if coolant_temp >= 212:
            scores["cooling_system_restriction"] += 0.6
            validations.append(
                "Critical overheat threshold reached (coolant_temp_f >= 212F): stop engine."
            )
        elif coolant_temp >= 200:
            scores["cooling_system_restriction"] += 0.35
            validations.append("coolant_temp_f elevated above normal operating range.")
        else:
            validations.append("coolant_temp_f not indicating an overheat event.")

    fuel_pressure = measurements.get("fuel_pressure_psi")
    if fuel_pressure is not None:
        if fuel_pressure < 35:
            scores["fuel_delivery_restriction"] += 0.4
            validations.append("fuel_pressure_psi below baseline threshold (<35 psi).")
        else:
            validations.append("fuel_pressure_psi not showing low-pressure restriction.")

    return validations


def _top_hypotheses(scores: dict[str, float]) -> list[tuple[str, float]]:
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    return [(code, round(score, 2)) for code, score in ranked if score > 0][:3]


def analyze_case(symptoms: list[str], measurements: dict[str, float] | None = None) -> DiagnosticAssessment:
    """Build evidence-grounded hypotheses from symptoms + measurements."""
    measurements = measurements or {}
    scores, normalized_symptoms = _score_symptoms(symptoms)
    validations = _apply_measurement_rules(scores, measurements)
    top = _top_hypotheses(scores)

    if not top:
        top = [("ignition_control_fault", 0.2)]

    ranked: list[RankedHypothesis] = []
    required_measurements: set[str] = set()
    for code, score in top:
        template = _HYPOTHESES[code]
        ranked.append(
            RankedHypothesis(
                code=code,
                title=template.title,
                score=score,
                rationale=[
                    "Ranked from reported symptoms and deterministic threshold checks.",
                    "Requires technician confirmation before component replacement.",
                ],
                recommended_tests=template.recommended_tests,
                required_tools=template.required_tools,
                safety_precautions=template.safety_precautions,
                supporting_references=template.supporting_references,
                suggested_repair_paths=template.suggested_repair_paths,
                post_repair_verification=template.post_repair_verification,
            )
        )
        required_measurements.update(template.required_measurements)

    provided = set(measurements.keys())
    missing_measurements = sorted(m for m in required_measurements if m not in provided)

    uncertainty_notes = []
    if missing_measurements:
        uncertainty_notes.append(
            "Missing measurements reduce certainty; capture listed values before major repairs."
        )
    if not normalized_symptoms:
        uncertainty_notes.append("No symptom narrative provided; classification confidence is limited.")
    if not validations:
        uncertainty_notes.append("No deterministic measurement checks were available.")

    top_score = ranked[0].score
    coverage = len(provided.intersection(required_measurements)) / max(len(required_measurements), 1)
    confidence = round(min(0.95, top_score * 0.7 + coverage * 0.3), 2)

    return DiagnosticAssessment(
        reported_symptoms=normalized_symptoms,
        available_measurements=measurements,
        ranked_hypotheses=ranked,
        missing_measurements=missing_measurements,
        deterministic_validations=validations,
        uncertainty_notes=uncertainty_notes,
        confidence=confidence,
    )

