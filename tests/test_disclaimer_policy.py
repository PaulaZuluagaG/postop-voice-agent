from agent.decision.disclaimer_policy import (
    is_triage_symptom_exchange,
    llm_text_contains_prescriptive_advice,
    patient_seeks_medical_information,
    should_replace_with_disclaimer,
)
from core.models import LLMTurnOutput, ResponseCategory


def test_patient_seeks_medical_information_detects_treatment_questions() -> None:
    assert patient_seeks_medical_information("¿Qué antibiótico debo tomar?") is True
    assert patient_seeks_medical_information("¿Cuándo puedo hacer ejercicio?") is True


def test_patient_seeks_medical_information_ignores_triage_answers() -> None:
    assert patient_seeks_medical_information("4") is False
    assert patient_seeks_medical_information("esta sanando") is False
    assert patient_seeks_medical_information("bien, sin dolor") is False


def test_llm_text_contains_prescriptive_advice() -> None:
    assert llm_text_contains_prescriptive_advice("Debe tomar antibióticos específicos.") is True
    assert (
        llm_text_contains_prescriptive_advice("Me alegra saber que su herida está sanando.")
        is False
    )


def test_should_not_disclaimer_for_wound_triage_answer() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        foco_sintoma="infeccion_herida",
        evidencia_suficiente=False,
        texto_paciente="Me alegra saber que su herida está sanando bien.",
        pregunta="¿Ha podido comer o beber algo?",
        fuentes=[],
    )
    assert should_replace_with_disclaimer("esta sanando", llm_output) is False


def test_should_not_disclaimer_for_numeric_pain_answer() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        foco_sintoma="dolor_abdominal",
        evidencia_suficiente=False,
        sintomas={"dolor_abdominal": 4.0},
        texto_paciente="Entiendo que siente un dolor de 4.",
        pregunta="¿Ha notado cambios en la herida?",
        fuentes=[],
    )
    assert should_replace_with_disclaimer("4", llm_output) is False


def test_should_disclaimer_for_ungrounded_treatment_question() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=False,
        texto_paciente="Debe tomar antibióticos específicos.",
        pregunta="¿Qué síntoma le preocupa más?",
        fuentes=[],
    )
    assert should_replace_with_disclaimer("¿Qué antibiótico debo tomar?", llm_output) is True


def test_should_not_disclaimer_for_reformulation_categories() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.NO_LO_SE,
        evidencia_suficiente=False,
        texto_paciente="No hay problema, le explico de otra forma.",
        pregunta="Del 0 al 10, ¿qué tan fuerte es su dolor?",
        fuentes=[],
    )
    assert should_replace_with_disclaimer("no sé", llm_output) is False


def test_should_not_disclaimer_when_grounded() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        evidencia_suficiente=True,
        texto_paciente="Según la guía, puede caminar con apoyo.",
        pregunta="¿Ha tenido fiebre?",
        fuentes=["src_1"],
    )
    assert should_replace_with_disclaimer("¿Puedo caminar?", llm_output) is False


def test_is_triage_symptom_exchange_for_qualitative_answer() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        foco_sintoma="infeccion_herida",
        texto_paciente="Gracias.",
        pregunta="¿Ha comido?",
    )
    assert is_triage_symptom_exchange(llm_output, "esta sanando") is True
