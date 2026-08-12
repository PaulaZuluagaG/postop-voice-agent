"""Determine whether RAG returned procedure-specific clinical evidence."""

from __future__ import annotations

from core.models import ProcedureScenario, RetrievedChunk
from core.scenarios import qdrant_filter_values


def has_procedure_specific_evidence(
    chunks: list[RetrievedChunk],
    scenario: ProcedureScenario,
    *,
    procedure_id: str | None = None,
) -> bool:
    """True when at least one chunk matches the registered procedure."""
    if scenario == ProcedureScenario.OTHER and not procedure_id:
        return bool(chunks)

    keys = set(qdrant_filter_values(procedure_id or scenario.value))
    return any(
        chunk.procedure_id in keys
        or chunk.procedure_scenario.value in keys
        or chunk.procedure_scenario == scenario
        for chunk in chunks
    )
