"""Determine whether RAG returned procedure-specific clinical evidence."""

from __future__ import annotations

from core.models import ProcedureScenario, RetrievedChunk


def has_procedure_specific_evidence(
    chunks: list[RetrievedChunk],
    scenario: ProcedureScenario,
) -> bool:
    """True when at least one non-general chunk matches the registered scenario."""
    if scenario == ProcedureScenario.GENERAL:
        return False
    return any(not chunk.is_general and chunk.procedure_scenario == scenario for chunk in chunks)
