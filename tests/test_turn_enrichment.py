from datetime import date

from agent.decision.turn_enrichment import (
    enrich_llm_output,
    parse_colloquial_scale_value,
    parse_minimized_pain_level,
    parse_numeric_pain_response,
    parse_temperature_response,
    parse_wound_infection_positive,
    parse_yes_no_response,
    take_first_question,
)
from agent.orchestrator import ConversationOrchestrator
from core.models import (
    LLMTurnOutput,
    ProcedureScenario,
    ResponseCategory,
    TurnRecord,
)
from tests.conftest import make_session


def test_parse_numeric_pain_response() -> None:
    assert parse_numeric_pain_response("8") == 8.0
    assert parse_numeric_pain_response(" 4/10 ") == 4.0
    assert parse_numeric_pain_response("mucho") is None


def test_parse_colloquial_scale_value() -> None:
    assert parse_colloquial_scale_value("cinco") == 5.0
    assert parse_colloquial_scale_value("como un 5") == 5.0
    assert parse_colloquial_scale_value("5 más o menos") == 5.0
    assert parse_colloquial_scale_value("por ahí un 3") == 3.0


def test_parse_temperature_response() -> None:
    assert parse_temperature_response("38.1") == 38.1
    assert parse_temperature_response("38,1") == 38.1
    assert parse_temperature_response("38 algo") == 38.0
    assert parse_temperature_response("treinta y ocho") == 38.0


def test_parse_minimized_pain_level() -> None:
    assert parse_minimized_pain_level("casi nada") == 2.5
    assert parse_minimized_pain_level("un poquito") == 2.5
    assert parse_minimized_pain_level("mucho dolor") is None


def test_parse_wound_infection_positive() -> None:
    from core.models import YesNo

    assert parse_wound_infection_positive("sale pus") == YesNo.SI
    assert parse_wound_infection_positive("líquido amarillo") == YesNo.SI
    assert parse_wound_infection_positive("esta sanando") is None


def test_take_first_question_keeps_only_one() -> None:
    chained = "¿Cómo está la herida? ¿Hay enrojecimiento, hinchazón o secreción?"
    assert take_first_question(chained) == "¿Cómo está la herida?"


def test_enrich_llm_output_fills_pain_when_agent_asked_scale() -> None:
    session = make_session()
    session.current_focal_symptom = "dolor_abdominal"
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
        texto_paciente="Gracias.",
        pregunta="¿Cómo está la herida? ¿Hay secreción?",
    )

    enriched = enrich_llm_output(session, "8", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.sintomas.get("dolor_abdominal") == 8.0
    assert enriched.pregunta == "¿Cómo está la herida?"


def test_enrich_llm_output_parses_colloquial_pain_phrase() -> None:
    session = make_session()
    session.current_focal_symptom = "dolor_abdominal"
    session.turns.append(
        TurnRecord(
            turn_number=1,
            patient_input="hola",
            agent_response="Del 0 al 10, ¿qué tan fuerte es su dolor?",
            rag_query="q",
        )
    )
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        texto_paciente="Gracias.",
        pregunta="¿Ha tenido fiebre?",
    )

    enriched = enrich_llm_output(session, "como un 5", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.sintomas.get("dolor_abdominal") == 5.0


def test_enrich_llm_output_parses_minimized_pain() -> None:
    session = make_session()
    session.current_focal_symptom = "dolor_abdominal"
    session.turns.append(
        TurnRecord(
            turn_number=1,
            patient_input="hola",
            agent_response="En una escala del 0 al 10, ¿qué nivel de dolor siente?",
            rag_query="q",
        )
    )
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        texto_paciente="De acuerdo.",
        pregunta="¿Ha tenido fiebre?",
    )

    enriched = enrich_llm_output(session, "casi nada", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.sintomas.get("dolor_abdominal") == 2.5


def test_enrich_llm_output_parses_colloquial_fever() -> None:
    session = make_session()
    session.current_focal_symptom = "fiebre"
    session.turns.append(
        TurnRecord(
            turn_number=1,
            patient_input="hola",
            agent_response="¿Ha tenido fiebre? ¿Cuál ha sido su temperatura?",
            rag_query="q",
        )
    )
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        texto_paciente="Gracias.",
        pregunta="¿Cómo está la herida?",
    )

    enriched = enrich_llm_output(
        session, "treinta y ocho", llm_output, reference_date=date(2026, 8, 8)
    )

    assert enriched.sintomas.get("fiebre") == 38.0


def test_enrich_llm_output_parses_wound_infection_colloquial() -> None:
    session = make_session(scenario=ProcedureScenario.TOTAL_JOINT_REPLACEMENT)
    session.current_focal_symptom = "infeccion_herida"
    session.turns.append(
        TurnRecord(
            turn_number=1,
            patient_input="hola",
            agent_response="¿Presenta supuración con pus en la herida operatoria?",
            rag_query="q",
        )
    )
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        texto_paciente="Entiendo.",
        pregunta="¿Ha tenido fiebre?",
    )

    enriched = enrich_llm_output(
        session,
        "sale líquido amarillo",
        llm_output,
        reference_date=date(2026, 8, 8),
    )

    assert enriched.sintomas.get("infeccion_herida") == "si"


def test_enrich_llm_output_does_not_overwrite_llm_value() -> None:
    session = make_session()
    session.current_focal_symptom = "dolor_abdominal"
    session.turns.append(
        TurnRecord(
            turn_number=1,
            patient_input="hola",
            agent_response="Del 0 al 10, ¿qué tan fuerte es su dolor?",
            rag_query="q",
        )
    )
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        foco_sintoma="dolor_abdominal",
        evidencia_suficiente=False,
        sintomas={"dolor_abdominal": 7.0},
        texto_paciente="Gracias.",
        pregunta="¿Ha tenido fiebre?",
    )

    enriched = enrich_llm_output(session, "como un 5", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.sintomas.get("dolor_abdominal") == 7.0


def test_parse_yes_no_response() -> None:
    from core.models import YesNo

    assert parse_yes_no_response("no") == YesNo.NO
    assert parse_yes_no_response(" Sí ") == YesNo.SI
    assert parse_yes_no_response("esta sanando") is None


def test_enrich_llm_output_fills_disnea_when_agent_asked_breathing() -> None:
    session = make_session()
    session.current_focal_symptom = "respiracion"
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
        texto_paciente="Entiendo, Paula.",
        pregunta="¿Ha podido movilizarse?",
    )

    enriched = enrich_llm_output(session, "no", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.sintomas.get("respiracion") == "no"


def test_enrich_llm_output_fills_vomiting_when_agent_asked_nausea() -> None:
    session = make_session()
    session.current_focal_symptom = "vomitos_episodios"
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
        texto_paciente="Entiendo.",
        pregunta="¿Ha podido movilizarse?",
    )

    enriched = enrich_llm_output(session, "si", llm_output, reference_date=date(2026, 8, 8))

    assert enriched.sintomas.get("vomitos_episodios") == "si"


def test_compose_response_skips_disclaimer_for_valid_numeric_pain() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        foco_sintoma="dolor_abdominal",
        evidencia_suficiente=False,
        sintomas={"dolor_abdominal": 4.0},
        texto_paciente="Entiendo que siente un dolor de 4.",
        pregunta="¿Ha notado cambios en la herida?",
        fuentes=[],
    )

    session = make_session()
    response = ConversationOrchestrator()._compose_response(
        session,
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
        foco_sintoma="infeccion_herida",
        evidencia_suficiente=False,
        texto_paciente="Me alegra saber que su herida está sanando bien.",
        pregunta="¿Ha podido comer o beber algo?",
        fuentes=[],
    )

    session = make_session()
    response = ConversationOrchestrator()._compose_response(
        session,
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

    session = make_session()
    response = ConversationOrchestrator()._compose_response(
        session,
        "¿Qué antibiótico debo tomar?",
        llm_output,
        registered_scenario=ProcedureScenario.APPENDICITIS,
    )

    assert "No tengo información" in response
    assert response.count("?") == 1
    assert response.endswith("¿Qué síntoma le preocupa más?")
