"""Tests for severity-aware call closure messages and summary flags."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from agent.messages import (
    ALERT_MESSAGE,
    GREEN_CLOSE_MESSAGE,
    YELLOW_CLOSE_MESSAGE,
    closure_message_for_severity,
)
from agent.orchestrator import ConversationOrchestrator
from agent.traceability.calls import CallLogService
from core.config import Settings
from core.models import (
    LLMTurnOutput,
    ProcedureScenario,
    ResponseCategory,
    SeverityLevel,
    TurnRecord,
)
from knowledge.protocol.loader import load_protocol_for_procedure
from tests.test_orchestrator import FakeLLM, FakeRetriever


def test_closure_message_for_severity() -> None:
    assert closure_message_for_severity(SeverityLevel.GREEN) == GREEN_CLOSE_MESSAGE
    assert closure_message_for_severity(SeverityLevel.YELLOW) == YELLOW_CLOSE_MESSAGE
    assert closure_message_for_severity(SeverityLevel.RED) == ALERT_MESSAGE


def test_orchestrator_yellow_closure_uses_vigilance_message() -> None:
    class YellowScoreLLM:
        def __init__(self) -> None:
            self._turn = 0

        def generate_turn(self, **kwargs):
            self._turn += 1
            if self._turn == 1:
                return LLMTurnOutput(
                    categoria=ResponseCategory.RESPUESTA_VALIDA,
                    foco_sintoma="fiebre",
                    evidencia_suficiente=True,
                    sintomas={"fiebre": 37.8},
                    texto_paciente="De acuerdo.",
                    pregunta="¿Cómo clasifica su dolor abdominal del 0 al 10?",
                    fuentes=["src_test"],
                )
            return LLMTurnOutput(
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                foco_sintoma="dolor_abdominal",
                evidencia_suficiente=True,
                sintomas={"dolor_abdominal": 5.0},
                texto_paciente="Gracias.",
                pregunta="¿Ha tenido náuseas?",
                fuentes=["src_test"],
            )

    settings = Settings(max_turns_per_call=2)
    orchestrator = ConversationOrchestrator(
        settings=settings,
        retriever=FakeRetriever(),
        llm=YellowScoreLLM(),
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="2026-08-05",
        call_id=uuid4(),
    )
    orchestrator.process_turn(session.call_id, "37.8")
    turn = orchestrator.process_turn(session.call_id, "5")

    assert session.current_severity == SeverityLevel.YELLOW
    assert session.alert_triggered is False
    assert "vigilancia" in turn.agent_response.lower()
    assert YELLOW_CLOSE_MESSAGE in turn.agent_response

    summary = orchestrator._build_summary(session, "max_turns_reached")
    assert summary.severity == SeverityLevel.YELLOW
    assert summary.follow_up_recommended is True
    assert summary.vigilancia_recomendada is True
    assert summary.physician_escalated is False


def test_orchestrator_red_closure_keeps_alert_message() -> None:
    class RedScoreLLM(FakeLLM):
        def generate_turn(self, **kwargs):
            return LLMTurnOutput(
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                foco_sintoma="fiebre",
                evidencia_suficiente=True,
                sintomas={"fiebre": 39.0},
                texto_paciente="Entiendo.",
                pregunta=None,
                fuentes=["src_test"],
            )

    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=RedScoreLLM(),
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="2026-08-05",
        call_id=uuid4(),
    )
    turn = orchestrator.process_turn(session.call_id, "39 grados")

    assert session.alert_triggered is True
    assert session.call_closed is True
    assert session.call_close_logged is True
    assert ALERT_MESSAGE in turn.agent_response

    summary = orchestrator._build_summary(session, "alert_triggered")
    assert summary.severity == SeverityLevel.RED
    assert summary.decision_label == "rojo"
    assert summary.physician_escalated is True
    assert summary.follow_up_recommended is False
    assert "evaluación presencial" in summary.next_steps.lower()


def test_alert_summary_stays_red_when_score_band_is_yellow() -> None:
    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=FakeLLM(),
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="2026-08-05",
        call_id=uuid4(),
    )
    session.alert_triggered = True
    session.cumulative_score = 10
    session.current_severity = SeverityLevel.YELLOW

    summary = orchestrator._build_summary(session, "alert_triggered")
    assert summary.severity == SeverityLevel.RED
    assert summary.decision_label == "rojo"
    assert summary.physician_escalated is True
    assert summary.follow_up_recommended is False
    assert "vigilancia" not in summary.next_steps.lower()


def test_orchestrator_alert_persists_call_close_event(tmp_path) -> None:
    from agent.traceability.logger import CallTraceLogger

    class RedScoreLLM(FakeLLM):
        def generate_turn(self, **kwargs):
            return LLMTurnOutput(
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                foco_sintoma="fiebre",
                evidencia_suficiente=True,
                sintomas={"fiebre": 39.0},
                texto_paciente="Entiendo.",
                pregunta=None,
                fuentes=["src_test"],
            )

    settings = Settings(calls_log_dir=tmp_path / "calls")
    trace = CallTraceLogger(settings)
    orchestrator = ConversationOrchestrator(
        settings=settings,
        retriever=FakeRetriever(),
        llm=RedScoreLLM(),
        trace_logger=trace,
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="2026-08-05",
        call_id=uuid4(),
    )

    orchestrator.process_turn(session.call_id, "39 grados")

    events = trace.read_call_log(session.call_id)
    assert any(event.get("event_type") == "call_close" for event in events)
    assert CallLogService(settings).get_call_summary(str(session.call_id)) is not None


def test_orchestrator_summary_escalates_when_wound_infection_reported_earlier() -> None:
    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=FakeLLM(),
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.TOTAL_JOINT_REPLACEMENT,
        surgery_date="2026-08-05",
        call_id=uuid4(),
    )
    session.turns.extend(
        [
            TurnRecord(
                turn_number=1,
                patient_input="No tengo fiebre",
                agent_response="¿Cómo está la herida?",
                rag_query="fiebre",
                symptoms={"fiebre": False, "dolor_intenso": 5},
            ),
            TurnRecord(
                turn_number=2,
                patient_input="La herida supura",
                agent_response="Gracias.",
                rag_query="herida",
                symptoms={"infeccion_herida": "si"},
                alert_triggered=False,
            ),
        ]
    )
    session.cumulative_score = 10
    session.current_severity = SeverityLevel.YELLOW
    session.alert_triggered = False

    summary = orchestrator._build_summary(session, "max_turns_reached")
    assert summary.severity == SeverityLevel.RED
    assert summary.decision_label == "rojo"
    assert summary.alert_triggered is True
    assert "evaluación presencial" in summary.next_steps.lower()
    assert "vigilancia" not in summary.next_steps.lower()


def test_protocol_thresholds_define_yellow_band_without_overlap() -> None:
    """All procedure protocols share a yellow band below red escalation."""
    for procedure_id in (
        "appendicitis",
        "cholecystitis",
        "colorectal-cancer",
        "cervical-cancer",
        "total-joint-replacement",
        "general",
    ):
        protocol, _ = load_protocol_for_procedure(procedure_id)
        assert protocol.thresholds.verde == 0
        assert protocol.thresholds.amarillo == 8
        assert protocol.thresholds.rojo == 15
        assert protocol.thresholds.amarillo < protocol.thresholds.rojo
