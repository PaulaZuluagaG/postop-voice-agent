from agent.llm.payload_normalizer import normalize_llm_turn_payload
from core.models import LLMTurnOutput, YesNo, coerce_episode_count, coerce_yes_no


def test_coerce_yes_no_from_bool() -> None:
    assert coerce_yes_no(False) == YesNo.NO
    assert coerce_yes_no(True) == YesNo.SI


def test_coerce_yes_no_from_strings() -> None:
    assert coerce_yes_no("no") == YesNo.NO
    assert coerce_yes_no("Sí") == YesNo.SI
    assert coerce_yes_no("false") == YesNo.NO


def test_normalize_llm_turn_payload_converts_bool_sintomas() -> None:
    payload = normalize_llm_turn_payload(
        {
            "categoria": "RESPUESTA_VALIDA",
            "texto_paciente": "Entiendo.",
            "sintomas": {"disnea": False, "sangrado": True},
        }
    )
    assert payload["sintomas"]["disnea"] == "no"
    assert payload["sintomas"]["sangrado"] == "si"


def test_normalize_llm_turn_payload_coerces_vomiting_yes_no() -> None:
    payload = normalize_llm_turn_payload(
        {
            "categoria": "RESPUESTA_VALIDA",
            "texto_paciente": "Entiendo.",
            "sintomas": {"vomitos": "si"},
        }
    )
    assert payload["sintomas"]["vomitos"] == "si"

    output = LLMTurnOutput.model_validate(payload)
    assert output.sintomas["vomitos"] == "si"


def test_normalize_llm_turn_payload_coerces_numeric_sintomas() -> None:
    payload = normalize_llm_turn_payload(
        {
            "categoria": "RESPUESTA_VALIDA",
            "texto_paciente": "Entiendo.",
            "sintomas": {"vomitos_episodios": 3, "dolor_abdominal": "9"},
        }
    )
    assert payload["sintomas"]["vomitos_episodios"] == 3
    assert payload["sintomas"]["dolor_abdominal"] == 9.0


def test_coerce_episode_count() -> None:
    assert coerce_episode_count("3") == 3
    assert coerce_episode_count(2) == 2
    assert coerce_episode_count("si") is None


def test_normalize_llm_turn_payload_strips_legacy_fields() -> None:
    payload = normalize_llm_turn_payload(
        {
            "categoria": "RESPUESTA_VALIDA",
            "texto_paciente": "Entiendo, Paula.",
            "pregunta": "¿Ha podido movilizarse?",
            "hechos": {"DISNEA": False},
            "foco": "dolor",
            "sintomas": {"respiracion": False},
        }
    )
    assert "hechos" not in payload
    assert "foco" not in payload
    assert payload["sintomas"]["respiracion"] == "no"

    output = LLMTurnOutput.model_validate(payload)
    assert output.sintomas["respiracion"] == "no"
