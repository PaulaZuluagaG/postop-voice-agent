"""Tests for compact conversation memory."""

from __future__ import annotations

from agent.memory.compact_memory import (
    build_compact_memory,
    format_accumulated_symptoms,
    merge_session_symptom_values,
)
from core.config import Settings
from core.models import (
    CallSessionState,
    LLMTurnOutput,
    ResponseCategory,
    TurnRecord,
)
from tests.conftest import make_session


def _session_with_turns(turn_count: int) -> CallSessionState:
    session = make_session()
    session.opening_message = "Hola, ¿cómo está su dolor del 0 al 10?"
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
                    sintomas={"dolor_abdominal": pain},
                    texto_paciente=f"Turno {index + 1}",
                    pregunta="¿Algún otro síntoma?",
                ),
            )
        )
    return session


def test_merge_session_symptom_values_uses_latest_values() -> None:
    session = _session_with_turns(3)
    session.turns[-1].llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        sintomas={"dolor_abdominal": 8.0, "fiebre": 38.2},
        texto_paciente="",
        pregunta="¿Fiebre?",
    )

    values = merge_session_symptom_values(session)

    assert values["dolor_abdominal"] == 8.0
    assert values["fiebre"] == 38.2


def test_format_accumulated_symptoms_renders_protocol_ids() -> None:
    session = make_session()
    session.turns.append(
        TurnRecord(
            turn_number=1,
            patient_input="38.2",
            agent_response="Gracias.",
            rag_query="query",
            llm_output=LLMTurnOutput(
                categoria=ResponseCategory.RESPUESTA_VALIDA,
                sintomas={"fiebre": 38.2, "disnea": "no"},
                texto_paciente="Gracias.",
                pregunta="¿Dolor?",
            ),
        )
    )

    rendered = format_accumulated_symptoms(session)

    assert "- fiebre: 38.2" in rendered
    assert "- disnea: no" in rendered


def test_build_compact_memory_limits_llm_history_window() -> None:
    session = _session_with_turns(5)
    settings = Settings(conversation_history_max_turns=2, rag_context_max_turns=1)

    memory = build_compact_memory(session, settings)

    assert "Turnos 1-3 omitidos" in memory.llm_history
    assert "Paciente: respuesta 4" in memory.llm_history
    assert "Paciente: respuesta 1" not in memory.llm_history
    assert memory.omitted_turn_count == 3


def test_build_compact_memory_keeps_full_symptoms_with_short_history() -> None:
    session = _session_with_turns(5)
    settings = Settings(conversation_history_max_turns=2, rag_context_max_turns=1)

    memory = build_compact_memory(session, settings)

    assert "- dolor_abdominal: 5.0" in memory.accumulated_facts


def test_build_compact_memory_rag_context_is_shorter_than_llm_history() -> None:
    session = _session_with_turns(4)
    settings = Settings(conversation_history_max_turns=3, rag_context_max_turns=1)

    memory = build_compact_memory(session, settings)

    assert "Agente (apertura)" not in memory.rag_context
    assert "Paciente: respuesta 4" in memory.rag_context
    assert "Paciente: respuesta 2" not in memory.rag_context
    assert len(memory.rag_context) < len(memory.llm_history)
