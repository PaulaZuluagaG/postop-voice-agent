from pathlib import Path
from uuid import uuid4

from agent.traceability.logger import CallTraceLogger
from api.services.calls import CallLogService
from core.config import Settings
from core.models import CallSummary, ProcedureScenario, SeverityLevel


def test_call_log_service_lists_and_reads_summaries(tmp_path: Path) -> None:
    settings = Settings(calls_log_dir=tmp_path / "calls")
    logger = CallTraceLogger(settings)
    call_id = uuid4()

    logger.log_call_start(
        call_id,
        procedure_id="appendicitis",
        procedure_scenario=ProcedureScenario.APPENDICITIS.value,
        postop_day=2,
        patient_name="María",
        patient_id="PAC-1",
    )
    logger.log_call_close(
        call_id,
        CallSummary(
            call_id=call_id,
            procedure_id="appendicitis",
            procedure_scenario=ProcedureScenario.APPENDICITIS,
            postop_day=2,
            patient_name="María",
            patient_id="PAC-1",
            final_score=5,
            severity=SeverityLevel.YELLOW,
            decision_label="amarillo",
            symptoms_reported={"fiebre": 38.1},
            next_steps="Vigilancia activa",
            clinical_summary="Resumen de prueba.",
            alert_triggered=False,
            sources_used=["guia.pdf"],
            turn_count=1,
            closed_reason="max_turns",
            turn_history=[],
        ),
    )

    service = CallLogService(settings)
    listed = service.list_recent_calls()
    assert len(listed) == 1
    assert listed[0]["call_id"] == str(call_id)
    assert listed[0]["patient_name"] == "María"
    assert listed[0]["decision_label"] == "amarillo"

    summary = service.get_call_summary(str(call_id))
    assert summary is not None
    assert summary.clinical_summary == "Resumen de prueba."
    assert summary.symptoms_reported == {"fiebre": 38.1}


def test_call_log_service_rewrites_source_ids_in_clinical_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(calls_log_dir=tmp_path / "calls")
    logger = CallTraceLogger(settings)
    call_id = uuid4()

    logger.log_call_start(
        call_id,
        procedure_id="appendicitis",
        procedure_scenario=ProcedureScenario.APPENDICITIS.value,
        postop_day=2,
        patient_name="María",
        patient_id="PAC-1",
    )
    logger.log_call_close(
        call_id,
        CallSummary(
            call_id=call_id,
            procedure_id="appendicitis",
            procedure_scenario=ProcedureScenario.APPENDICITIS,
            postop_day=2,
            patient_name="María",
            patient_id="PAC-1",
            final_score=5,
            severity=SeverityLevel.YELLOW,
            decision_label="amarillo",
            symptoms_reported={"fiebre": 38.1},
            next_steps="Vigilancia activa",
            clinical_summary=("Paciente María. Fuentes clínicas consultadas: src_abc123."),
            alert_triggered=False,
            sources_used=["src_abc123"],
            turn_count=1,
            closed_reason="max_turns",
            turn_history=[],
        ),
    )

    monkeypatch.setattr(
        "api.services.calls.resolve_source_labels",
        lambda source_ids, settings=None: {"src_abc123": "guia_apendicitis.pdf"},
    )

    summary = CallLogService(settings).get_call_summary(str(call_id))
    assert summary is not None
    assert "guia_apendicitis.pdf" in summary.clinical_summary
    assert "src_abc123" not in summary.clinical_summary
