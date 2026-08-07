from uuid import uuid4

from agent.orchestrator import ConversationOrchestrator
from core.models import (
    DocumentType,
    LLMTurnOutput,
    PatientFacts,
    ProcedureScenario,
    RetrievedChunk,
    SeverityLevel,
)
from knowledge.retrieval.retriever import ContextualRetriever


class FakeRetriever(ContextualRetriever):
    def retrieve(self, patient_message, *, procedure_scenario, postop_day, conversation_context=""):
        chunk = RetrievedChunk(
            chunk_id="chunk-1",
            source_id="src_test",
            text="El dolor leve es esperable en las primeras horas.",
            token_count=10,
            chunk_index=0,
            page_start=1,
            page_end=1,
            procedure_scenario=procedure_scenario,
            document_type=DocumentType.GUIDE,
            language="es",
            file_name="guia.pdf",
            score=0.9,
        )
        return "query", [chunk], 5.0


class FakeLLM:
    def generate_turn(self, **kwargs):
        return LLMTurnOutput(
            patient_message="Entiendo su molestia. ¿El dolor empeora al respirar?",
            extracted_symptoms=PatientFacts(pain=6.0),
            cited_source_ids=["src_test"],
        )


class AlertLLM:
    def generate_turn(self, **kwargs):
        return LLMTurnOutput(
            patient_message="Lo siento, esto no debería decir el LLM.",
            extracted_symptoms=PatientFacts(pain=2.0),
            implicit_alert=True,
        )


def test_orchestrator_uses_python_alert_message() -> None:
    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=AlertLLM(),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.CHOLECYSTITIS,
        postop_day=1,
        call_id=uuid4(),
    )
    turn = orchestrator.process_turn(session.call_id, "Me siento muy mal")
    assert turn.alert_triggered is True
    assert "equipo de salud" in turn.agent_response.lower()
    assert "Lo siento, esto no debería" not in turn.agent_response


def test_orchestrator_no_evidence_disclaimer() -> None:
    class EmptyRetriever(FakeRetriever):
        def retrieve(self, *args, **kwargs):
            return "query", [], 1.0

    class NoEvidenceLLM:
        def generate_turn(self, **kwargs):
            return LLMTurnOutput(
                patient_message="Debe tomar antibióticos específicos.",
                no_evidence_topics=["antibióticos"],
            )

    orchestrator = ConversationOrchestrator(
        retriever=EmptyRetriever(),
        llm=NoEvidenceLLM(),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        postop_day=3,
        call_id=uuid4(),
    )
    turn = orchestrator.process_turn(session.call_id, "¿Qué antibiótico debo tomar?")
    assert "No tengo información" in turn.agent_response
    assert turn.alert_triggered is False


def test_orchestrator_accumulates_score_across_turns() -> None:
    class HighPainLLM:
        def __init__(self) -> None:
            self._calls = 0

        def generate_turn(self, **kwargs):
            self._calls += 1
            pain = 6.0 if self._calls == 1 else 8.0
            return LLMTurnOutput(
                patient_message="Gracias por la información.",
                extracted_symptoms=PatientFacts(pain=pain),
            )

    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=HighPainLLM(),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.BREAST_CANCER,
        postop_day=1,
        call_id=uuid4(),
    )
    first = orchestrator.process_turn(session.call_id, "Me duele un poco")
    second = orchestrator.process_turn(session.call_id, "Ahora me duele mucho más")
    assert first.turn_score == 4
    assert second.turn_score == 10
    assert second.cumulative_score == 14
    assert second.severity == SeverityLevel.YELLOW
