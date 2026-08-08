from datetime import date
from uuid import uuid4

from agent.orchestrator import ConversationOrchestrator
from core.models import (
    ClinicalAxis,
    ClinicalFacts,
    DocumentType,
    LLMTurnOutput,
    ProcedureScenario,
    ResponseCategory,
    RetrievedChunk,
    SeverityLevel,
    YesNo,
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
    def generate_opening(self, **kwargs):
        if kwargs.get("has_procedure_evidence"):
            return LLMTurnOutput(
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                texto_paciente="",
                pregunta="¿Ha notado enrojecimiento alrededor de la herida de la apendicectomía?",
            )
        return LLMTurnOutput(
            categoria=ResponseCategory.RESPUESTA_VALIDA,
            texto_paciente="",
            pregunta="Del 0 al 10, ¿qué tan fuerte es su dolor?",
        )

    def generate_turn(self, **kwargs):
        return LLMTurnOutput(
            categoria=ResponseCategory.RESPUESTA_VALIDA,
            foco=ClinicalAxis.DOLOR,
            evidencia_suficiente=True,
            hechos=ClinicalFacts(dolor_0_10=6.0),
            texto_paciente="Entiendo su molestia.",
            pregunta="¿El dolor empeora al respirar?",
            fuentes=["src_test"],
        )


class AlertLLM:
    def generate_turn(self, **kwargs):
        return LLMTurnOutput(
            categoria=ResponseCategory.ALERTA_IMPLICITA,
            foco=ClinicalAxis.HERIDA,
            evidencia_suficiente=True,
            hechos=ClinicalFacts(sangreado=YesNo.SI),
            texto_paciente="Lo siento, esto no debería decir el LLM.",
            pregunta=None,
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
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                evidencia_suficiente=False,
                texto_paciente="Debe tomar antibióticos específicos.",
                pregunta="¿Qué síntoma le preocupa más?",
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
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                foco=ClinicalAxis.DOLOR,
                hechos=ClinicalFacts(dolor_0_10=pain),
                texto_paciente="Gracias por la información.",
                pregunta="¿Ha tenido fiebre?",
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


def test_start_call_with_registration_leaves_opening_for_begin_triage() -> None:
    session = ConversationOrchestrator(reference_date=date(2026, 8, 8)).start_call(
        patient_name="María",
        patient_id="P-001",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        procedure_name="Apendicitis",
        surgery_date="ayer",
    )
    assert session.postop_day == 2
    assert session.opening_message is None


def test_begin_triage_without_procedure_evidence() -> None:
    class GeneralOnlyRetriever(FakeRetriever):
        def retrieve(self, *args, **kwargs):
            chunk = RetrievedChunk(
                chunk_id="chunk-general",
                source_id="src_general",
                text="Guía general postoperatoria.",
                token_count=10,
                chunk_index=0,
                page_start=1,
                page_end=1,
                procedure_scenario=ProcedureScenario.GENERAL,
                document_type=DocumentType.GUIDE,
                language="es",
                file_name="general.pdf",
                is_general=True,
                score=0.8,
            )
            return "query", [chunk], 1.0

    orchestrator = ConversationOrchestrator(
        retriever=GeneralOnlyRetriever(),
        llm=FakeLLM(),
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        patient_name="María",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        procedure_name="Apendicitis",
        surgery_date="ayer",
        call_id=uuid4(),
    )
    opening = orchestrator.begin_triage(session.call_id)
    assert "María" in opening
    assert "No tengo información específica sobre Apendicitis" in opening
    assert "triaje general" in opening.lower()
    assert opening.count("?") == 1
    assert "Del 0 al 10" in opening


def test_begin_triage_with_procedure_evidence() -> None:
    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=FakeLLM(),
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        patient_name="María",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        procedure_name="Apendicitis",
        surgery_date="ayer",
        call_id=uuid4(),
    )
    opening = orchestrator.begin_triage(session.call_id)
    assert "Sí cuento con guías clínicas sobre Apendicitis" in opening
    assert "apendicectomía" in opening.lower()
    assert opening.count("?") == 1
