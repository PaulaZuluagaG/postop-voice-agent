from datetime import date
from uuid import uuid4

from agent.decision.turn_enrichment import (
    enrich_llm_output,
    parse_numeric_pain_response,
    parse_yes_no_response,
    take_first_question,
)
from agent.orchestrator import ConversationOrchestrator
from core.models import (
    CallSessionState,
    ClinicalAxis,
    ClinicalFacts,
    LLMTurnOutput,
    ProcedureScenario,
    ResponseCategory,
    TurnRecord,
    YesNo,
)


def test_parse_numeric_pain_response() -> None:
    assert parse_numeric_pain_response("8") == 8.0
    assert parse_numeric_pain_response(" 4/10 ") == 4.0
    assert parse_numeric_pain_response("mucho") is None


def test_take_first_question_keeps_only_one() -> None:
    chained = "¿Cómo está la herida? ¿Hay enrojecimiento, hinchazón o secreción?"
    assert take_first_question(chained) == "¿Cómo está la herida?"


def test_enrich_llm_output_fills_pain_when_agent_asked_scale() -> None:
    session = CallSessionState(
        call_id=uuid4(),
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        postop_day=2,
    )
    session.turns.append(
        TurnRecord(
            turn_number=1,
            patient_input="ayer",
            agent_response=(
                "¿Podría decirme, en una escala del 0 al 10, "
                "qué nivel de dolor siente en este momento?"
            ),
            rag_query="q",
        )
    )
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        hechos=ClinicalFacts(),
        texto_paciente="Gracias.",
        pregunta="¿Cómo está la herida? ¿Hay secreción?",
    )

    enriched = enrich_llm_output(session, "8", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.hechos.dolor_0_10 == 8.0
    assert enriched.pregunta == "¿Cómo está la herida?"


def test_parse_yes_no_response() -> None:
    assert parse_yes_no_response("no") == YesNo.NO
    assert parse_yes_no_response(" Sí ") == YesNo.SI
    assert parse_yes_no_response("esta sanando") is None


def test_enrich_llm_output_fills_disnea_when_agent_asked_breathing() -> None:
    session = CallSessionState(
        call_id=uuid4(),
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        postop_day=2,
    )
    session.turns.append(
        TurnRecord(
            turn_number=1,
            patient_input="no",
            agent_response=("¿Ha notado alguna dificultad para respirar o le ha faltado el aire?"),
            rag_query="q",
        )
    )
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        hechos=ClinicalFacts(),
        texto_paciente="Entiendo, Paula.",
        pregunta="¿Ha podido movilizarse?",
    )

    enriched = enrich_llm_output(session, "no", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.hechos.disnea == YesNo.NO
    assert enriched.foco == ClinicalAxis.RESPIRACION


def test_enrich_llm_output_fills_vomiting_when_agent_asked_nausea() -> None:
    session = CallSessionState(
        call_id=uuid4(),
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        postop_day=2,
    )
    session.turns.append(
        TurnRecord(
            turn_number=2,
            patient_input="9",
            agent_response="¿Ha tenido náuseas o vómitos desde la cirugía?",
            rag_query="q",
        )
    )
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        hechos=ClinicalFacts(),
        texto_paciente="Entiendo.",
        pregunta="¿Ha podido movilizarse?",
    )

    enriched = enrich_llm_output(session, "si", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.hechos.vomitos == YesNo.SI
    assert enriched.foco == ClinicalAxis.DIGESTIVO


def test_compose_response_skips_disclaimer_for_valid_numeric_pain() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        foco=ClinicalAxis.DOLOR,
        evidencia_suficiente=False,
        hechos=ClinicalFacts(dolor_0_10=4.0),
        texto_paciente="Entiendo que siente un dolor de 4.",
        pregunta="¿Ha notado cambios en la herida?",
        fuentes=[],
    )

    response = ConversationOrchestrator._compose_response(
        "4",
        llm_output,
        registered_scenario=ProcedureScenario.APPENDICITIS,
    )

    assert "No tengo información" not in response
    assert "dolor de 4" in response
    assert response.endswith("¿Ha notado cambios en la herida?")


def test_compose_response_skips_disclaimer_for_wound_answer() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        foco=ClinicalAxis.HERIDA,
        evidencia_suficiente=False,
        hechos=ClinicalFacts(),
        texto_paciente="Me alegra saber que su herida está sanando bien.",
        pregunta="¿Ha podido comer o beber algo?",
        fuentes=[],
    )

    response = ConversationOrchestrator._compose_response(
        "esta sanando",
        llm_output,
        registered_scenario=ProcedureScenario.APPENDICITIS,
    )

    assert "No tengo información" not in response
    assert "sanando" in response.lower()
    assert response.count("?") == 1


def test_compose_response_uses_disclaimer_without_double_question() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        texto_paciente="Debe tomar antibióticos específicos.",
        pregunta="¿Qué síntoma le preocupa más?",
        fuentes=[],
    )

    response = ConversationOrchestrator._compose_response(
        "¿Qué antibiótico debo tomar?",
        llm_output,
        registered_scenario=ProcedureScenario.APPENDICITIS,
    )

    assert "No tengo información" in response
    assert response.count("?") == 1
    assert response.endswith("¿Qué síntoma le preocupa más?")
