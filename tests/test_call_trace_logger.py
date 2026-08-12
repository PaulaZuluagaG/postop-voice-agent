import json
from pathlib import Path
from uuid import uuid4

from agent.traceability.logger import CallTraceLogger
from core.config import Settings
from core.models import CallSummary, ProcedureScenario, SeverityLevel, TurnRecord


def test_call_trace_logger_writes_pretty_json_files(tmp_path: Path) -> None:
    settings = Settings(calls_log_dir=tmp_path / "calls")
    logger = CallTraceLogger(settings)
    call_id = uuid4()

    logger.log_call_start(
        call_id,
        procedure_id="appendicitis",
        procedure_scenario=ProcedureScenario.APPENDICITIS.value,
        postop_day=2,
        patient_name="Paula Zuluaga",
    )
    logger.log_event(call_id, "triage_opening", {"opening_message": "Hola Paula"})
    logger.log_turn(
        call_id,
        TurnRecord(
            turn_number=1,
            patient_input="Tengo fiebre",
            agent_response="¿Cuál es su temperatura?",
            rag_query="fiebre",
        ),
    )
    logger.log_call_close(
        call_id,
        CallSummary(
            call_id=call_id,
            procedure_id="appendicitis",
            procedure_scenario=ProcedureScenario.APPENDICITIS,
            postop_day=2,
            final_score=0,
            severity=SeverityLevel.GREEN,
            alert_triggered=False,
            sources_used=[],
            turn_count=1,
            closed_reason="max_turns",
            turn_history=[],
        ),
    )

    root = tmp_path / "calls" / str(call_id)
    summary_path = root / "summary" / "events.json"
    turn_path = root / "turns" / "turn_001.json"

    assert summary_path.exists()
    assert turn_path.exists()

    summary_text = summary_path.read_text(encoding="utf-8")
    turn_text = turn_path.read_text(encoding="utf-8")

    assert "\n  " in summary_text
    assert "\n  " in turn_text
    assert summary_text.count('"event_type"') == 3

    summary_payload = json.loads(summary_text)
    turn_payload = json.loads(turn_text)

    assert isinstance(summary_payload, list)
    assert len(summary_payload) == 3
    assert turn_payload["event_type"] == "turn"

    events = logger.read_call_log(call_id)
    assert len(events) == 4
    assert [event["event_type"] for event in events] == [
        "call_start",
        "triage_opening",
        "turn",
        "call_close",
    ]
