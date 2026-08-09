from agent.llm.payload_normalizer import normalize_llm_turn_payload
from core.models import ClinicalFacts, LLMTurnOutput, YesNo, coerce_episode_count, coerce_yes_no


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


def test_clinical_facts_accepts_vomiting_presence() -> None:
    facts = ClinicalFacts.model_validate({"VOMITOS": "si"})
    assert facts.vomitos == YesNo.SI
    assert facts.resolved_vomiting_count() == 1


def test_clinical_facts_accepts_vomiting_episodes() -> None:
    facts = ClinicalFacts.model_validate({"VOMITOS_EPISODIOS": 3})
    assert facts.vomitos_episodios == 3
    assert facts.resolved_vomiting_count() == 3


def test_clinical_facts_accepts_string_pain_score() -> None:
    facts = ClinicalFacts.model_validate({"DOLOR_0_10": "9"})
    assert facts.dolor_0_10 == 9.0


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


def test_normalize_llm_turn_payload_coerces_vomiting_yes_no() -> None:
    payload = normalize_llm_turn_payload(
        {
            "categoria": "RESPUESTA_VALIDA",
            "texto_paciente": "Entiendo.",
            "hechos": {"VOMITOS": "si"},
        }
    )
    assert payload["hechos"]["VOMITOS"] == "si"

    output = LLMTurnOutput.model_validate(payload)
    assert output.hechos.vomitos == YesNo.SI
    assert output.hechos.resolved_vomiting_count() == 1


def test_normalize_llm_turn_payload_routes_legacy_vomiting_count() -> None:
    payload = normalize_llm_turn_payload(
        {
            "categoria": "RESPUESTA_VALIDA",
            "texto_paciente": "Entiendo.",
            "hechos": {"VOMITOS": 3},
        }
    )
    assert payload["hechos"]["VOMITOS"] == "si"
    assert payload["hechos"]["VOMITOS_EPISODIOS"] == 3

    output = LLMTurnOutput.model_validate(payload)
    assert output.hechos.resolved_vomiting_count() == 3


def test_coerce_episode_count() -> None:
    assert coerce_episode_count("3") == 3
    assert coerce_episode_count(2) == 2
    assert coerce_episode_count("si") is None


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
