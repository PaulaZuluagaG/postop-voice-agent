"""Compact conversation memory: accumulated facts + rolling dialogue window."""

from __future__ import annotations

from dataclasses import dataclass

from core.config import Settings
from core.models import CallSessionState, ClinicalFacts, YesNo


@dataclass(frozen=True)
class CompactMemoryView:
    """Structured memory payload for LLM prompts and RAG query enrichment."""

    accumulated_facts: str
    llm_history: str
    rag_context: str
    omitted_turn_count: int


_FACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("dolor_0_10", "Dolor"),
    ("fiebre_c", "Fiebre"),
    ("disnea", "Disnea"),
    ("sangreado", "Sangrado"),
    ("vomitos", "Vómitos (presencia)"),
    ("vomitos_episodios", "Vómitos (episodios)"),
    ("confusion", "Confusión"),
)


def merge_session_facts(session: CallSessionState) -> ClinicalFacts:
    """Merge structured facts from all completed turns (latest value wins)."""
    merged = ClinicalFacts()
    updates: dict[str, object] = {}
    for turn in session.turns:
        if turn.llm_output is None:
            continue
        facts = turn.llm_output.hechos
        for field_name, _label in _FACT_FIELDS:
            value = getattr(facts, field_name)
            if value is not None:
                updates[field_name] = value
    if updates:
        merged = merged.model_copy(update=updates)
    return merged


def format_accumulated_facts(facts: ClinicalFacts) -> str:
    """Render merged clinical facts as a compact bullet list."""
    lines: list[str] = []
    for field_name, label in _FACT_FIELDS:
        value = getattr(facts, field_name)
        if value is None:
            continue
        if field_name == "dolor_0_10":
            lines.append(f"- {label}: {value}/10")
        elif field_name == "fiebre_c":
            lines.append(f"- {label}: {value} °C")
        elif field_name in {"disnea", "sangreado", "confusion", "vomitos"}:
            assert isinstance(value, YesNo)
            lines.append(f"- {label}: {'sí' if value == YesNo.SI else 'no'}")
        else:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines) if lines else "- (ningún hecho clínico registrado aún)"


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
        f"consulta hechos acumulados arriba.)"
    )


def build_compact_memory(session: CallSessionState, settings: Settings) -> CompactMemoryView:
    """Build LLM history, RAG context, and accumulated facts for one turn."""
    facts_block = format_accumulated_facts(merge_session_facts(session))

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
