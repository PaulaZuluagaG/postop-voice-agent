from agent.llm.payload_normalizer import normalize_llm_turn_payload
from core.models import ClinicalFacts, LLMTurnOutput, YesNo, coerce_yes_no


def test_coerce_yes_no_from_bool() -> None:
    assert coerce_yes_no(False) == YesNo.NO
    assert coerce_yes_no(True) == YesNo.SI


def test_coerce_yes_no_from_strings() -> None:
    assert coerce_yes_no("no") == YesNo.NO
    assert coerce_yes_no("Sí") == YesNo.SI
    assert coerce_yes_no("false") == YesNo.NO


def test_clinical_facts_accepts_bool_disnea() -> None:
    facts = ClinicalFacts.model_validate({"DISNEA": False})
    assert facts.disnea == YesNo.NO


def test_normalize_llm_turn_payload_converts_bool_hechos() -> None:
    payload = normalize_llm_turn_payload(
        {
            "categoria": "RESPUESTA_VALIDA",
            "texto_paciente": "Entiendo.",
            "hechos": {"DISNEA": False, "SANGREADO": True},
        }
    )
    assert payload["hechos"]["DISNEA"] == "no"
    assert payload["hechos"]["SANGREADO"] == "si"


def test_llm_turn_output_validates_after_bool_normalization() -> None:
    payload = normalize_llm_turn_payload(
        {
            "categoria": "RESPUESTA_VALIDA",
            "texto_paciente": "Entiendo, Paula.",
            "pregunta": "¿Ha podido movilizarse?",
            "hechos": {"DISNEA": False},
        }
    )
    output = LLMTurnOutput.model_validate(payload)
    assert output.hechos.disnea == YesNo.NO
