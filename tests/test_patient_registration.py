from datetime import date

from agent.orchestrator import ConversationOrchestrator
from core.models import ProcedureScenario
from scripts.patient_registration import registration_from_args


def test_registration_from_args_resolves_surgery_date() -> None:
    registration = registration_from_args(
        patient_name="María",
        patient_id="P-001",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        procedure_name=None,
        surgery_date="ayer",
        reference_date=date(2026, 8, 8),
    )
    assert registration.surgery_date == "2026-08-07"
    assert registration.procedure_name == "Apendicitis"


def test_start_call_with_registration_sets_triage_context() -> None:
    registration = registration_from_args(
        patient_name="María",
        patient_id="P-001",
        procedure_scenario=ProcedureScenario.CHOLECYSTITIS,
        procedure_name="Colecistitis",
        surgery_date="2026-08-06",
        reference_date=date(2026, 8, 8),
    )
    session = ConversationOrchestrator(reference_date=date(2026, 8, 8)).start_call(
        procedure_scenario=registration.procedure_scenario,
        patient_name=registration.patient_name,
        patient_id=registration.patient_id,
        procedure_name=registration.procedure_name,
        surgery_date=registration.surgery_date,
    )
    assert session.patient_id == "P-001"
    assert session.postop_day == 3
    assert session.opening_message is None
