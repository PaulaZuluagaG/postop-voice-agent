"""Post-LLM enrichment: colloquial parsing fallback and question shaping."""

from __future__ import annotations

import re
from datetime import date

from agent.decision.intake import normalize_procedure_text
from agent.decision.protocol_triage import coerce_symptom_response
from agent.decision.session_protocol import protocol_from_session
from core.models import CallSessionState, LLMTurnOutput, YesNo

_PAIN_SCALE_HINTS: tuple[str, ...] = (
    "0 al 10",
    "1 al 10",
    "del 0 al 10",
    "del 1 al 10",
    "escala del 0 al 10",
    "escala del 1 al 10",
    "nivel de dolor",
    "tan fuerte es su dolor",
    "qué tan fuerte es su dolor",
    "qué tan intenso es el dolor",
    "intensidad de su dolor",
)

_FEVER_HINTS: tuple[str, ...] = (
    "fiebre",
    "temperatura",
    "grados centigrados",
    "grados celsius",
)

_MINIMIZED_PAIN_HINTS: tuple[str, ...] = (
    "casi nada",
    "un poquito",
    "muy poquito",
    "poquito",
    "apenas",
    "casi nada de dolor",
)

_WOUND_INFECTION_HINTS: tuple[str, ...] = (
    "liquido amarillo",
    "líquido amarillo",
    "pus",
    "supura",
    "supuracion",
    "supuración",
    "secrecion amarill",
    "secreción amarill",
    "sale pus",
    "mal olor",
)

_SPANISH_SCALE_WORDS: dict[str, int] = {
    "cero": 0,
    "uno": 1,
    "un": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}

_FEVER_WORD_PHRASES: dict[str, float] = {
    "treinta y cinco": 35.0,
    "treinta y seis": 36.0,
    "treinta y siete": 37.0,
    "treinta y ocho": 38.0,
    "treinta y nueve": 39.0,
    "cuarenta": 40.0,
    "cuarenta y uno": 41.0,
    "cuarenta y dos": 42.0,
}

_NUMERIC_PAIN = re.compile(r"^\s*(\d{1,2})(?:\s*/\s*10)?\s*$")
_COLOQUIAL_SCALE_NUMBER = re.compile(
    r"(?:como\s+un\s+|mas\s+o\s+menos\s+|más\s+o\s+menos\s+|cerca\s+de\s+|por\s+ahi\s+|por\s+ahí\s+)?"
    r"(\d{1,2})(?:\s*/\s*10)?",
    re.IGNORECASE,
)
_TEMPERATURE_DECIMAL = re.compile(r"\b(3[4-9]|4[0-2])(?:[.,](\d))?\b")
_TEMPERATURE_ALGO = re.compile(r"\b(3[4-9]|4[0-2])\s+algo\b", re.IGNORECASE)
_YES_NO_RESPONSE = re.compile(
    r"^\s*(s[ií]|no|yes|true|false)\s*\.?$",
    re.IGNORECASE,
)
_NUMERIC_EPISODES = re.compile(r"^\s*(\d+)\s*$")

_MINIMIZED_PAIN_LEVEL = 2.5


def _last_agent_message(session: CallSessionState) -> str:
    if session.turns:
        return session.turns[-1].agent_response
    return session.opening_message or ""


def _asks_pain_scale(agent_message: str) -> bool:
    normalized = normalize_procedure_text(agent_message)
    return any(hint in normalized for hint in _PAIN_SCALE_HINTS)


def _asks_fever_or_temperature(agent_message: str, symptom_id: str | None) -> bool:
    normalized_id = normalize_procedure_text(symptom_id or "")
    if "fiebre" in normalized_id or "temperatura" in normalized_id:
        return True
    normalized = normalize_procedure_text(agent_message)
    return any(hint in normalized for hint in _FEVER_HINTS)


def _is_wound_infection_symptom(symptom_id: str) -> bool:
    normalized = normalize_procedure_text(symptom_id)
    return "infeccion" in normalized or "incision" in normalized


def _symptom_value_present(
    sintomas: dict[str, object],
    symptom_id: str,
    symptom_type: str,
) -> bool:
    if symptom_id not in sintomas:
        return False
    raw = sintomas[symptom_id]
    if raw is None:
        return False
    return coerce_symptom_response(raw, symptom_type) is not None


def parse_numeric_pain_response(patient_message: str) -> float | None:
    match = _NUMERIC_PAIN.match(patient_message.strip().replace(",", "."))
    if not match:
        return None
    value = float(match.group(1))
    if 0 <= value <= 10:
        return value
    return None


def parse_colloquial_scale_value(patient_message: str, *, max_value: float = 10) -> float | None:
    """Parse digits or Spanish words for 0-10 scales and colloquial numeric phrases."""
    direct = parse_numeric_pain_response(patient_message)
    if direct is not None:
        return direct

    normalized = normalize_procedure_text(patient_message)
    match = _COLOQUIAL_SCALE_NUMBER.search(normalized)
    if match:
        value = float(match.group(1))
        if 0 <= value <= max_value:
            return value

    for word, number in _SPANISH_SCALE_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", normalized):
            if 0 <= number <= max_value:
                return float(number)

    return None


def parse_minimized_pain_level(patient_message: str) -> float | None:
    normalized = normalize_procedure_text(patient_message)
    if any(hint in normalized for hint in _MINIMIZED_PAIN_HINTS):
        return _MINIMIZED_PAIN_LEVEL
    return None


def parse_temperature_response(patient_message: str) -> float | None:
    text = patient_message.strip().replace(",", ".")
    normalized = normalize_procedure_text(patient_message)

    algo_match = _TEMPERATURE_ALGO.search(normalized)
    if algo_match:
        return float(algo_match.group(1))

    decimal_match = _TEMPERATURE_DECIMAL.search(text)
    if decimal_match:
        whole = float(decimal_match.group(1))
        fraction = decimal_match.group(2)
        if fraction:
            return whole + float(fraction) / 10.0
        return whole

    for phrase, value in _FEVER_WORD_PHRASES.items():
        if phrase in normalized:
            return value

    return None


def parse_wound_infection_positive(patient_message: str) -> YesNo | None:
    normalized = normalize_procedure_text(patient_message)
    if any(hint in normalized for hint in _WOUND_INFECTION_HINTS):
        return YesNo.SI
    return None


def parse_yes_no_response(patient_message: str) -> YesNo | None:
    match = _YES_NO_RESPONSE.match(patient_message.strip())
    if not match:
        return None
    token = match.group(1).strip().lower().replace("í", "i")
    if token in {"si", "yes", "true"}:
        return YesNo.SI
    return YesNo.NO


def parse_episode_count_response(patient_message: str) -> int | None:
    match = _NUMERIC_EPISODES.match(patient_message.strip())
    if not match:
        word_value = parse_colloquial_scale_value(patient_message, max_value=100)
        if word_value is not None and word_value == int(word_value):
            return int(word_value)
        return None
    return int(match.group(1))


def take_first_question(pregunta: str | None) -> str | None:
    """Keep a single question when the model chains several."""
    if not pregunta:
        return None
    stripped = pregunta.strip()
    if "?" not in stripped:
        return stripped

    first, *_rest = stripped.split("?")
    question = first.strip()
    if not question:
        return stripped
    return f"{question}?"


def _apply_colloquial_fallback(
    session: CallSessionState,
    patient_message: str,
    sintomas: dict[str, object],
    *,
    focal_id: str | None,
    focal_symptom,
) -> None:
    """Fill missing focal symptom values from colloquial patient text (LLM values win)."""
    if focal_id is None or focal_symptom is None:
        return
    if _symptom_value_present(sintomas, focal_id, focal_symptom.type):
        return

    agent_message = _last_agent_message(session)

    if focal_symptom.type == "binary" and _is_wound_infection_symptom(focal_id):
        infection = parse_wound_infection_positive(patient_message)
        if infection is not None:
            sintomas[focal_id] = infection.value
            return

    if focal_symptom.type == "numeric":
        if _asks_fever_or_temperature(agent_message, focal_id):
            temperature = parse_temperature_response(patient_message)
            if temperature is not None:
                sintomas[focal_id] = temperature
                return

        if _asks_pain_scale(agent_message):
            minimized = parse_minimized_pain_level(patient_message)
            if minimized is not None:
                sintomas[focal_id] = minimized
                return
            scale_value = parse_colloquial_scale_value(patient_message)
            if scale_value is not None:
                sintomas[focal_id] = scale_value
                return

        episodes = parse_episode_count_response(patient_message)
        if episodes is not None:
            sintomas[focal_id] = episodes
            return

        scale_value = parse_colloquial_scale_value(patient_message)
        if scale_value is not None:
            sintomas[focal_id] = scale_value
            return

    elif focal_symptom.type == "binary":
        yes_no = parse_yes_no_response(patient_message)
        if yes_no is not None:
            sintomas[focal_id] = yes_no.value
            return
        if _is_wound_infection_symptom(focal_id):
            infection = parse_wound_infection_positive(patient_message)
            if infection is not None:
                sintomas[focal_id] = infection.value
                return
    else:
        yes_no = parse_yes_no_response(patient_message)
        if yes_no is not None:
            sintomas[focal_id] = yes_no.value
            return
        episodes = parse_episode_count_response(patient_message)
        if episodes is not None:
            sintomas[focal_id] = episodes
            return
        scale_value = parse_colloquial_scale_value(patient_message)
        if scale_value is not None:
            sintomas[focal_id] = scale_value


def enrich_llm_output(
    session: CallSessionState,
    patient_message: str,
    llm_output: LLMTurnOutput,
    *,
    reference_date: date | None = None,
) -> LLMTurnOutput:
    """Apply deterministic corrections without replacing valid LLM extractions."""
    del reference_date
    output_updates: dict[str, object] = {}
    sintomas = dict(llm_output.sintomas)

    protocol = protocol_from_session(session)
    symptoms_by_id = {symptom.id: symptom for symptom in protocol.symptoms}
    focal_id = llm_output.foco_sintoma or session.current_focal_symptom
    focal_symptom = symptoms_by_id.get(focal_id) if focal_id else None

    _apply_colloquial_fallback(
        session,
        patient_message,
        sintomas,
        focal_id=focal_id,
        focal_symptom=focal_symptom,
    )

    if focal_id and focal_id not in sintomas:
        yes_no = parse_yes_no_response(patient_message)
        if yes_no is not None:
            sintomas[focal_id] = yes_no.value

    for symptom_id, raw in list(sintomas.items()):
        symptom = symptoms_by_id.get(symptom_id)
        if symptom is None:
            continue
        coerced = coerce_symptom_response(raw, symptom.type)
        if coerced is not None:
            sintomas[symptom_id] = coerced

    output_updates["sintomas"] = sintomas
    output_updates["pregunta"] = take_first_question(llm_output.pregunta)

    if focal_id and not llm_output.foco_sintoma:
        output_updates["foco_sintoma"] = focal_id

    return llm_output.model_copy(update=output_updates)
