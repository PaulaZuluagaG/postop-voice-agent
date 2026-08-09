"""Post-LLM enrichment: numeric pain fallback and question shaping."""

from __future__ import annotations

import re
from datetime import date

from agent.decision.intake import normalize_procedure_text
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

_DYSPNEA_HINTS: tuple[str, ...] = (
    "respir",
    "disnea",
    "falta el aire",
    "ahogo",
    "oxigeno",
)
_BLEEDING_HINTS: tuple[str, ...] = (
    "sangr",
    "sangre",
    "hemorrag",
)
_VOMITING_HINTS: tuple[str, ...] = (
    "vomit",
    "vómit",
    "vomito",
    "nausea",
    "náusea",
    "nauseas",
    "náuseas",
)
_CONFUSION_HINTS: tuple[str, ...] = (
    "confus",
    "desorient",
    "alerta mental",
)
_EPISODE_HINTS: tuple[str, ...] = (
    "episod",
    "cuant",
    "cuánt",
    "veces",
    "cuantos",
    "cuántos",
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


def _detect_yes_no_axis(agent_message: str) -> tuple[str, ClinicalAxis] | None:
    normalized = normalize_procedure_text(agent_message)
    if any(hint in normalized for hint in _DYSPNEA_HINTS):
        return ("disnea", ClinicalAxis.RESPIRACION)
    if any(hint in normalized for hint in _BLEEDING_HINTS):
        return ("sangreado", ClinicalAxis.HERIDA)
    if any(hint in normalized for hint in _VOMITING_HINTS):
        return ("vomitos", ClinicalAxis.DIGESTIVO)
    if any(hint in normalized for hint in _CONFUSION_HINTS):
        return ("confusion", ClinicalAxis.NINGUNO)
    return None


def _asks_episode_count(agent_message: str) -> bool:
    normalized = normalize_procedure_text(agent_message)
    return any(hint in normalized for hint in _EPISODE_HINTS)


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
    del reference_date  # reserved for future enrichment; registration sets session context
    hechos_updates: dict[str, object] = {}
    output_updates: dict[str, object] = {}

    if llm_output.hechos.dolor_0_10 is None and _asks_pain_scale(_last_agent_message(session)):
        pain = parse_numeric_pain_response(patient_message)
        if pain is not None:
            hechos_updates["dolor_0_10"] = pain

    yes_no = parse_yes_no_response(patient_message)
    if yes_no is not None:
        axis_target = _detect_yes_no_axis(_last_agent_message(session))
        if axis_target is not None:
            field_name, axis = axis_target
            current = getattr(llm_output.hechos, field_name)
            if current is None:
                hechos_updates[field_name] = yes_no
                if llm_output.foco == ClinicalAxis.NINGUNO and axis != ClinicalAxis.NINGUNO:
                    output_updates["foco"] = axis

    if llm_output.hechos.vomitos_episodios is None and _asks_episode_count(
        _last_agent_message(session)
    ):
        episodes = parse_episode_count_response(patient_message)
        if episodes is not None:
            hechos_updates["vomitos_episodios"] = episodes
            if llm_output.hechos.vomitos is None:
                hechos_updates["vomitos"] = YesNo.SI if episodes > 0 else YesNo.NO
            if llm_output.foco == ClinicalAxis.NINGUNO:
                output_updates["foco"] = ClinicalAxis.DIGESTIVO

    output_updates["pregunta"] = take_first_question(llm_output.pregunta)

    if hechos_updates:
        hechos = llm_output.hechos.model_copy(update=hechos_updates)
        output_updates["hechos"] = hechos
        if (
            hechos.dolor_0_10 is not None
            and llm_output.foco == ClinicalAxis.NINGUNO
            and "foco" not in output_updates
        ):
            output_updates["foco"] = ClinicalAxis.DOLOR

    return llm_output.model_copy(update=output_updates)
