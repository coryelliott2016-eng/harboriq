import pytest

from app.services.marine_diagnostics import analyze_case

pytestmark = pytest.mark.no_db


def test_overheat_case_ranks_cooling_first_and_sets_critical_validation():
    result = analyze_case(
        symptoms=["Engine overheat alarm at cruise RPM"],
        measurements={"coolant_temp_f": 214.0},
    )

    top = result.ranked_hypotheses[0]
    assert top.code == "cooling_system_restriction"
    assert any("stop engine" in item.lower() for item in result.deterministic_validations)
    assert any("shut down" in item.lower() for item in top.safety_precautions)


def test_low_running_voltage_boosts_charging_fault_and_marks_missing_rest_voltage():
    result = analyze_case(
        symptoms=["Battery light on and low voltage warning"],
        measurements={"battery_voltage_running_v": 12.8},
    )

    codes = [item.code for item in result.ranked_hypotheses]
    assert "charging_system_fault" in codes[:2]
    assert "battery_voltage_rest_v" in result.missing_measurements


def test_no_signal_input_returns_low_confidence_with_uncertainty():
    result = analyze_case(symptoms=[], measurements={})
    assert result.confidence < 0.3
    assert result.ranked_hypotheses
    assert result.uncertainty_notes


def test_additional_measurements_increase_confidence_for_same_symptoms():
    sparse = analyze_case(symptoms=["Engine stalls under load"], measurements={})
    rich = analyze_case(
        symptoms=["Engine stalls under load"],
        measurements={"fuel_pressure_psi": 30.0},
    )
    assert rich.confidence > sparse.confidence
