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
    assert not result.ranked_hypotheses
    assert result.uncertainty_notes
    assert any("insufficient evidence" in note.lower() for note in result.uncertainty_notes)


def test_additional_measurements_increase_confidence_for_same_symptoms():
    sparse = analyze_case(symptoms=["Engine stalls under load"], measurements={})
    rich = analyze_case(
        symptoms=["Engine stalls under load"],
        measurements={"fuel_pressure_psi": 30.0},
    )
    assert rich.confidence > sparse.confidence


def test_mutating_hypothesis_lists_does_not_change_later_assessments():
    result = analyze_case(symptoms=["Engine overheat alarm"])
    later_result = analyze_case(symptoms=["Engine overheat alarm"])
    list_fields = (
        "recommended_tests",
        "required_tools",
        "safety_precautions",
        "supporting_references",
        "suggested_repair_paths",
        "post_repair_verification",
    )

    for field in list_fields:
        getattr(result.ranked_hypotheses[0], field).clear()

    for field in list_fields:
        assert getattr(later_result.ranked_hypotheses[0], field)


def test_normal_coolant_measurement_reduces_overheat_hypothesis_confidence():
    sparse = analyze_case(symptoms=["Engine overheat alarm"])
    measured = analyze_case(
        symptoms=["Engine overheat alarm"],
        measurements={"coolant_temp_f": 180.0},
    )

    assert measured.ranked_hypotheses[0].code == "cooling_system_restriction"
    assert measured.confidence < sparse.confidence


def test_duplicate_symptoms_do_not_inflate_score_or_confidence():
    single = analyze_case(symptoms=["Engine overheat alarm"])
    repeated = analyze_case(
        symptoms=["Engine overheat alarm", "Engine overheat alarm", "engine OVERHEAT alarm"]
    )

    assert repeated.ranked_hypotheses[0].score == single.ranked_hypotheses[0].score
    assert repeated.confidence == single.confidence


def test_symptom_only_confidence_is_capped():
    result = analyze_case(
        symptoms=[
            "Engine stalls under load",
            "Engine stalls at idle",
            "Engine stalls at cruise",
            "Engine stalls after warmup",
        ]
    )

    assert result.confidence <= 0.5
