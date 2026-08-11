"""Post-LLM enrichment: numeric pain fallback and question shaping."""

from __future__ import annotations

import re
from datetime import date

from agent.decision.intake import normalize_procedure_text
from agent.decision.protocol_triage import coerce_symptom_response
from agent.decision.session_protocol import protocol_from_session
from core.models import CallSessionState, ClinicalAxis, ClinicalFacts, LLMTurnOutput, YesNo

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
)

_NUMERIC_PAIN = re.compile(r"^\s*(\d{1,2})(?:\s*/\s*10)?\s*$")
_YES_NO_RESPONSE = re.compile(
    r"^\s*(s[ií]|no|yes|true|false)\s*\.?$",
    re.IGNORECASE,
)
_NUMERIC_EPISODES = re.compile(r"^\s*(\d+)\s*$")


def _last_agent_message(session: CallSessionState) -> str:
    if session.turns:
        return session.turns[-1].agent_response
    return session.opening_message or ""


def _asks_pain_scale(agent_message: str) -> bool:
    normalized = normalize_procedure_text(agent_message)
    return any(hint in normalized for hint in _PAIN_SCALE_HINTS)


def parse_numeric_pain_response(patient_message: str) -> float | None:
    match = _NUMERIC_PAIN.match(patient_message.strip().replace(",", "."))
    if not match:
        return None
    value = float(match.group(1))
    if 0 <= value <= 10:
        return value
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
        return None
    return int(match.group(1))


def has_structured_facts(hechos: ClinicalFacts) -> bool:
    return any(
        (
            hechos.dolor_0_10 is not None,
            hechos.fiebre_c is not None,
            hechos.disnea is not None,
            hechos.sangreado is not None,
            hechos.vomitos is not None,
            hechos.vomitos_episodios is not None,
            hechos.confusion is not None,
        )
    )


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


def enrich_llm_output(
    session: CallSessionState,
    patient_message: str,
    llm_output: LLMTurnOutput,
    *,
    reference_date: date | None = None,
) -> LLMTurnOutput:
    """Apply deterministic corrections without replacing valid LLM extractions."""
    del reference_date
    hechos_updates: dict[str, object] = {}
    output_updates: dict[str, object] = {}
    sintomas = dict(llm_output.sintomas)

    protocol = protocol_from_session(session)
    symptoms_by_id = {symptom.id: symptom for symptom in protocol.symptoms}
    focal_id = llm_output.foco_sintoma or session.current_focal_symptom
    focal_symptom = symptoms_by_id.get(focal_id) if focal_id else None

    if focal_symptom is not None and focal_id not in sintomas:
        if focal_symptom.type == "numeric":
            if _asks_pain_scale(_last_agent_message(session)):
                pain = parse_numeric_pain_response(patient_message)
                if pain is not None:
                    sintomas[focal_id] = pain
            else:
                episodes = parse_episode_count_response(patient_message)
                if episodes is not None:
                    sintomas[focal_id] = episodes
                else:
                    numeric = parse_numeric_pain_response(patient_message)
                    if numeric is not None:
                        sintomas[focal_id] = numeric
        elif focal_symptom.type == "binary":
            yes_no = parse_yes_no_response(patient_message)
            if yes_no is not None:
                sintomas[focal_id] = yes_no.value
        else:
            yes_no = parse_yes_no_response(patient_message)
            if yes_no is not None:
                sintomas[focal_id] = yes_no.value
            else:
                episodes = parse_episode_count_response(patient_message)
                if episodes is not None:
                    sintomas[focal_id] = episodes
                else:
                    numeric = parse_numeric_pain_response(patient_message)
                    if numeric is not None:
                        sintomas[focal_id] = numeric

    if llm_output.hechos.dolor_0_10 is None and _asks_pain_scale(_last_agent_message(session)):
        pain = parse_numeric_pain_response(patient_message)
        if pain is not None:
            hechos_updates["dolor_0_10"] = pain
            sintomas.setdefault("dolor", pain)

    yes_no = parse_yes_no_response(patient_message)
    if yes_no is not None and focal_id and focal_id not in sintomas:
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

    if hechos_updates:
        output_updates["hechos"] = llm_output.hechos.model_copy(update=hechos_updates)
        if hechos_updates.get("dolor_0_10") is not None and llm_output.foco == ClinicalAxis.NINGUNO:
            output_updates.setdefault("foco", ClinicalAxis.DOLOR)

    return llm_output.model_copy(update=output_updates)
