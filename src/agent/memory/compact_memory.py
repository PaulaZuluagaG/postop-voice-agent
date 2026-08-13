"""Compact conversation memory: accumulated facts + rolling dialogue window."""

from __future__ import annotations

from dataclasses import dataclass

from agent.decision.protocol_triage import extract_symptom_values
from agent.decision.session_protocol import protocol_from_session
from core.config import Settings
from core.models import CallSessionState, YesNo, coerce_yes_no
from knowledge.protocol.models import SymptomDefinition


@dataclass(frozen=True)
class CompactMemoryView:
    """Structured memory payload for LLM prompts and RAG query enrichment."""

    accumulated_facts: str
    llm_history: str
    rag_context: str
    omitted_turn_count: int


def merge_session_symptom_values(session: CallSessionState) -> dict[str, object]:
    """Merge protocol symptom values from all completed turns (latest value wins)."""
    merged: dict[str, object] = {}
    for turn in session.turns:
        if turn.llm_output is None:
            continue
        for symptom_id, value in extract_symptom_values(turn.llm_output).items():
            merged[symptom_id] = value
    return merged


def _format_symptom_value(symptom: SymptomDefinition | None, value: object) -> str:
    if symptom is not None and symptom.type == "binary":
        yn = coerce_yes_no(value)
        if yn == YesNo.SI:
            return "sí"
        if yn == YesNo.NO:
            return "no"
    return str(value)


def format_accumulated_symptoms(session: CallSessionState) -> str:
    """Render merged protocol symptom values as a compact bullet list."""
    values = merge_session_symptom_values(session)
    if not values:
        return "- (ningún síntoma registrado aún)"

    protocol = protocol_from_session(session)
    symptoms_by_id = {symptom.id: symptom for symptom in protocol.symptoms}
    lines: list[str] = []
    for symptom_id in sorted(values):
        value = values[symptom_id]
        symptom = symptoms_by_id.get(symptom_id)
        label = symptom_id
        if symptom is not None and symptom.type == "numeric" and symptom_id.startswith("dolor"):
            lines.append(f"- {label}: {_format_symptom_value(symptom, value)}/10")
        else:
            lines.append(f"- {label}: {_format_symptom_value(symptom, value)}")
    return "\n".join(lines)


def _format_dialogue_lines(
    session: CallSessionState,
    *,
    include_opening: bool,
    max_turns: int | None,
) -> tuple[list[str], int]:
    """Return dialogue lines and how many older turns were omitted."""
    total_turns = len(session.turns)
    if max_turns is None or max_turns <= 0 or total_turns <= max_turns:
        start_index = 0
    else:
        start_index = total_turns - max_turns

    lines: list[str] = []
    if include_opening and session.opening_message and start_index == 0:
        lines.append(f"Agente (apertura): {session.opening_message}")

    for turn in session.turns[start_index:]:
        lines.append(f"Paciente: {turn.patient_input}")
        lines.append(f"Agente: {turn.agent_response}")

    omitted = start_index
    return lines, omitted


def _format_omission_note(omitted_turn_count: int) -> str:
    if omitted_turn_count <= 0:
        return ""
    return (
        f"(Turnos 1-{omitted_turn_count} omitidos del historial; "
        f"consulta síntomas acumulados arriba.)"
    )


def build_compact_memory(session: CallSessionState, settings: Settings) -> CompactMemoryView:
    """Build LLM history, RAG context, and accumulated symptoms for one turn."""
    facts_block = format_accumulated_symptoms(session)

    llm_lines, llm_omitted = _format_dialogue_lines(
        session,
        include_opening=True,
        max_turns=settings.conversation_history_max_turns,
    )
    llm_parts: list[str] = []
    omission_note = _format_omission_note(llm_omitted)
    if omission_note:
        llm_parts.append(omission_note)
    llm_parts.extend(llm_lines)
    llm_history = "\n".join(llm_parts) if llm_parts else "(inicio de llamada)"

    rag_lines, _rag_omitted = _format_dialogue_lines(
        session,
        include_opening=False,
        max_turns=settings.rag_context_max_turns,
    )
    rag_context = "\n".join(rag_lines)

    return CompactMemoryView(
        accumulated_facts=facts_block,
        llm_history=llm_history,
        rag_context=rag_context,
        omitted_turn_count=llm_omitted,
    )
