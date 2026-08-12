from datetime import date

from agent.decision.intake import parse_postop_timepoint
from agent.orchestrator import ConversationOrchestrator
from core.models import ProcedureScenario
from scripts.patient_registration import registration_from_args, registration_from_frontend


def test_registration_from_args_resolves_surgery_date() -> None:
    registration = registration_from_args(
        patient_name="María",
        patient_id="P-001",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="ayer",
        reference_date=date(2026, 8, 8),
    )
    assert registration.surgery_date == "2026-08-07"
    assert registration.postop_day == 2
    assert registration.procedure_label == "Apendicitis"


def test_registration_from_frontend_accepts_postop_day() -> None:
    registration = registration_from_frontend(
        {
            "name": "Paula",
            "patientId": "PAC-003",
            "postopDay": 7,
            "procedure": "appendicitis",
        }
    )
    assert registration.postop_day == 7
    assert registration.patient_id == "PAC-003"


def test_registration_from_frontend_rejects_invalid_postop_day() -> None:
    try:
        registration_from_frontend(
            {
                "name": "Paula",
                "patientId": "PAC-003",
                "postopDay": 2,
                "procedure": "appendicitis",
            }
        )
    except ValueError as exc:
        assert "inválido" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for invalid postop day")


def test_start_call_with_postop_day_skips_surgery_date() -> None:
    registration = registration_from_frontend(
        {
            "name": "María",
            "patientId": "P-001",
            "postopDay": 14,
            "procedure": "cholecystitis",
        }
    )
    session = ConversationOrchestrator(reference_date=date(2026, 8, 8)).start_call(
        procedure_scenario=registration.procedure_scenario,
        patient_name=registration.patient_name,
        patient_id=registration.patient_id,
        postop_day=registration.postop_day,
    )
    assert session.patient_id == "P-001"
    assert session.postop_day == 14
    assert session.surgery_date is None


def test_detect_procedure_mismatch_flags_different_surgery() -> None:
    from agent.decision.intake import detect_procedure_mismatch

    mismatch = detect_procedure_mismatch(
        "Tuve una artroplastia de rodilla el mes pasado",
        ProcedureScenario.APPENDICITIS,
    )
    assert mismatch == ProcedureScenario.TOTAL_JOINT_REPLACEMENT


def test_parse_postop_timepoint_accepts_string_values() -> None:
    assert parse_postop_timepoint("3") == 3
