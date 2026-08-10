"""Tests for compact conversation memory."""

from __future__ import annotations

from uuid import uuid4

from agent.memory.compact_memory import (
    build_compact_memory,
    format_accumulated_facts,
    merge_session_facts,
)
from core.config import Settings
from core.models import (
    CallSessionState,
    ClinicalFacts,
    LLMTurnOutput,
    ProcedureScenario,
    ResponseCategory,
    TurnRecord,
    YesNo,
)


def _session_with_turns(turn_count: int) -> CallSessionState:
    session = CallSessionState(
        call_id=uuid4(),
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        postop_day=2,
        opening_message="Hola, ¿cómo está su dolor del 0 al 10?",
    )
    for index in range(turn_count):
        pain = float(index + 1)
        session.turns.append(
            TurnRecord(
                turn_number=index + 1,
                patient_input=f"respuesta {index + 1}",
                agent_response=f"Gracias, turno {index + 1}. ¿Algún otro síntoma?",
                rag_query="query",
                llm_output=LLMTurnOutput(
                    categoria=ResponseCategory.RESPUESTA_VALIDA,
                    hechos=ClinicalFacts(dolor_0_10=pain),
                    texto_paciente=f"Turno {index + 1}",
                    pregunta="¿Algún otro síntoma?",
                ),
            )
        )
    return session


def test_merge_session_facts_uses_latest_values() -> None:
    session = _session_with_turns(3)
    session.turns[-1].llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        hechos=ClinicalFacts(dolor_0_10=8.0, disnea=YesNo.NO),
        texto_paciente="",
        pregunta="¿Fiebre?",
    )

    facts = merge_session_facts(session)

    assert facts.dolor_0_10 == 8.0
    assert facts.disnea == YesNo.NO


def test_format_accumulated_facts_renders_spanish_labels() -> None:
    rendered = format_accumulated_facts(
        ClinicalFacts(dolor_0_10=6.0, disnea=YesNo.NO, fiebre_c=38.2)
    )
    assert "- Dolor: 6.0/10" in rendered
    assert "- Disnea: no" in rendered
    assert "- Fiebre: 38.2 °C" in rendered


def test_build_compact_memory_limits_llm_history_window() -> None:
    session = _session_with_turns(5)
    settings = Settings(conversation_history_max_turns=2, rag_context_max_turns=1)

    memory = build_compact_memory(session, settings)

    assert "Turnos 1-3 omitidos" in memory.llm_history
    assert "Paciente: respuesta 4" in memory.llm_history
    assert "Paciente: respuesta 1" not in memory.llm_history
    assert memory.omitted_turn_count == 3


def test_build_compact_memory_keeps_full_facts_with_short_history() -> None:
    session = _session_with_turns(5)
    settings = Settings(conversation_history_max_turns=2, rag_context_max_turns=1)

    memory = build_compact_memory(session, settings)

    assert "- Dolor: 5.0/10" in memory.accumulated_facts


def test_build_compact_memory_rag_context_is_shorter_than_llm_history() -> None:
    session = _session_with_turns(4)
    settings = Settings(conversation_history_max_turns=3, rag_context_max_turns=1)

    memory = build_compact_memory(session, settings)

    assert "Agente (apertura)" not in memory.rag_context
    assert "Paciente: respuesta 4" in memory.rag_context
    assert "Paciente: respuesta 2" not in memory.rag_context
    assert len(memory.rag_context) < len(memory.llm_history)
