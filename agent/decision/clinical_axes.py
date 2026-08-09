"""Clinical axis coverage tracking for triage conversations."""

from __future__ import annotations

from core.models import ClinicalAxis, LLMTurnOutput, ResponseCategory

TRIAGE_AXES: frozenset[ClinicalAxis] = frozenset(
    {
        ClinicalAxis.DOLOR,
        ClinicalAxis.HERIDA,
        ClinicalAxis.DIGESTIVO,
        ClinicalAxis.RESPIRACION,
        ClinicalAxis.MOVILIDAD,
    }
)


def pending_axes(covered: set[ClinicalAxis]) -> list[ClinicalAxis]:
    return sorted(
        (axis for axis in TRIAGE_AXES if axis not in covered),
        key=lambda axis: axis.value,
    )


def update_covered_axes(
    covered: set[ClinicalAxis],
    llm_output: LLMTurnOutput,
) -> set[ClinicalAxis]:
    """Mark axes as covered from structured facts and valid responses."""
    updated = set(covered)
    facts = llm_output.hechos

    if facts.dolor_0_10 is not None:
        updated.add(ClinicalAxis.DOLOR)
    if facts.sangreado is not None:
        updated.add(ClinicalAxis.HERIDA)
    if facts.vomitos is not None or facts.vomitos_episodios is not None:
        updated.add(ClinicalAxis.DIGESTIVO)
    if facts.disnea is not None:
        updated.add(ClinicalAxis.RESPIRACION)
    if llm_output.categoria == ResponseCategory.RESPUESTA_VALIDA and llm_output.foco in TRIAGE_AXES:
        updated.add(llm_output.foco)

    return updated
