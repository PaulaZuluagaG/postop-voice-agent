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
    def retrieve(
        self, patient_message, *, procedure_id, postop_day, conversation_context="", **kwargs
    ):
        chunk = RetrievedChunk(
            chunk_id="chunk-1",
            source_id="src_test",
            text="El dolor leve es esperable en las primeras horas.",
            token_count=10,
            chunk_index=0,
            page_start=1,
            page_end=1,
            procedure_id=procedure_id,
            procedure_scenario=ProcedureScenario.APPENDICITIS,
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


class AlertLLM(FakeLLM):
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
            pain = 6.0 if self._calls == 1 else 7.0
            return LLMTurnOutput(
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                foco=ClinicalAxis.DOLOR,
                foco_sintoma="dolor_abdominal",
                hechos=ClinicalFacts(dolor_0_10=pain),
                sintomas={"dolor_abdominal": pain},
                texto_paciente="Gracias por la información.",
                pregunta="¿Ha tenido fiebre?",
            )

    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=HighPainLLM(),
        reference_date=date(2026, 8, 10),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="2026-08-07",
        call_id=uuid4(),
    )
    first = orchestrator.process_turn(session.call_id, "Me duele un poco")
    second = orchestrator.process_turn(session.call_id, "Ahora me duele mucho más")
    assert first.base_score == 4
    assert second.base_score == 4
    assert second.cumulative_score == 8
    assert second.severity == SeverityLevel.YELLOW


def test_orchestrator_closes_call_after_max_turns() -> None:
    from core.config import Settings

    class TurnTrackingLLM:
        def generate_turn(self, **kwargs):
            turno = kwargs.get("turno", 1)
            max_turnos = kwargs.get("max_turnos", 8)
            if turno >= max_turnos:
                return LLMTurnOutput(
                    categoria=ResponseCategory.RESPUESTA_VALIDA,
                    texto_paciente="Gracias por su tiempo, que esté muy bien.",
                    pregunta=None,
                )
            return LLMTurnOutput(
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                texto_paciente="Entendido.",
                pregunta="¿Ha tenido fiebre?",
            )

    settings = Settings(max_turns_per_call=3)
    orchestrator = ConversationOrchestrator(
        settings=settings,
        retriever=FakeRetriever(),
        llm=TurnTrackingLLM(),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        call_id=uuid4(),
    )
    for message in ("Bien", "Regular", "Con dolor"):
        orchestrator.process_turn(session.call_id, message)

    assert session.turn_count == 3
    assert session.call_closed is True
    summary = orchestrator._build_summary(session, "llm_closure")
    assert summary.turn_count == 3
    assert "Gracias por su tiempo" in session.turns[-1].agent_response


def test_orchestrator_appends_farewell_when_max_turns_reached_without_closure() -> None:
    from agent.messages import MAX_TURNS_CLOSE_MESSAGE
    from core.config import Settings

    class AlwaysQuestionLLM:
        def generate_turn(self, **kwargs):
            return LLMTurnOutput(
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                texto_paciente="Entendido.",
                pregunta="¿Ha tenido fiebre?",
            )

    settings = Settings(max_turns_per_call=2)
    orchestrator = ConversationOrchestrator(
        settings=settings,
        retriever=FakeRetriever(),
        llm=AlwaysQuestionLLM(),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        call_id=uuid4(),
    )
    orchestrator.process_turn(session.call_id, "Bien")
    orchestrator.process_turn(session.call_id, "Regular")

    assert session.call_closed is True
    assert MAX_TURNS_CLOSE_MESSAGE in session.turns[-1].agent_response


def test_build_user_prompt_includes_final_turn_closure_instructions() -> None:
    from agent.llm.prompts import build_user_prompt

    prompt = build_user_prompt(
        patient_name="María",
        procedimiento="Apendicitis",
        dia_postop=2,
        covered_symptom_ids=set(),
        pending_symptoms=[],
        alert_signs=[],
        puntaje_total=0,
        turno=8,
        max_turnos=8,
        historial="",
        hechos_acumulados="(ninguno)",
        patient_text="Estoy bien",
        evidence_block="",
        reference_date="2026-08-10",
    )

    assert "Cierre de llamada" in prompt
    assert "turno final 8/8" in prompt
    assert "`pregunta = null`" in prompt


def test_start_call_with_registration_leaves_opening_for_begin_triage() -> None:
    session = ConversationOrchestrator(reference_date=date(2026, 8, 8)).start_call(
        patient_name="María",
        patient_id="P-001",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="ayer",
    )
    assert session.postop_day == 2
    assert session.opening_message is None


def test_begin_triage_without_procedure_evidence() -> None:
    class EmptyRetriever(FakeRetriever):
        def retrieve(self, *args, **kwargs):
            return "query", [], 1.0

    orchestrator = ConversationOrchestrator(
        retriever=EmptyRetriever(),
        llm=FakeLLM(),
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        patient_name="María",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="ayer",
        call_id=uuid4(),
    )
    opening = orchestrator.begin_triage(session.call_id)
    assert "María" in opening
    assert "No tengo información específica sobre Apendicitis" in opening
    assert "triaje general" in opening.lower()
    assert opening.count("?") == 1
    assert "dolor" in opening.lower()


def test_begin_triage_with_procedure_evidence() -> None:
    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=FakeLLM(),
        reference_date=date(2026, 8, 8),
    )
    session = orchestrator.start_call(
        patient_name="María",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        surgery_date="ayer",
        call_id=uuid4(),
    )
    opening = orchestrator.begin_triage(session.call_id)
    assert "Sí cuento con guías clínicas sobre Apendicitis" in opening
    assert "apendicectomía" in opening.lower()
    assert opening.count("?") == 1


def test_orchestrator_procedure_mismatch_notice() -> None:
    orchestrator = ConversationOrchestrator(
        retriever=FakeRetriever(),
        llm=FakeLLM(),
    )
    session = orchestrator.start_call(
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        call_id=uuid4(),
    )
    turn = orchestrator.process_turn(
        session.call_id,
        "Después de mi artroplastia de rodilla me duele mucho la herida",
    )
    assert "no tengo documentación" in turn.agent_response.lower()
    assert "Reemplazo articular" in turn.agent_response
    assert "Apendicitis" in turn.agent_response
