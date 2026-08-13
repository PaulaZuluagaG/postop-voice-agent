"""Protocol-specific retrieval helpers."""

from __future__ import annotations

from core.config import Settings, get_settings
from core.models import RetrievedChunk
from core.scenarios import procedure_display_label
from knowledge.retrieval.retriever import ContextualRetriever

PROTOCOL_BASE_QUERIES: tuple[str, ...] = (
    "Síntomas principales, complicaciones postoperatorias, signos de alarma, "
    "niveles de dolor, fiebre y criterios de urgencia médica.",
    "Dolor, fiebre, náuseas, vómitos, sangrado, infección de herida y "
    "cuidados en casa el primer día postoperatorio.",
    "Signos de alarma que requieren consulta urgente o emergencia después de cirugía.",
)

PROTOCOL_POSTOP_DAY = 1


def protocol_queries_for(procedure_id: str) -> tuple[str, ...]:
    """Build the multi-query set for a procedure."""
    label = procedure_display_label(procedure_id)
    specific = (
        f"Complicaciones y cuidados postoperatorios específicos de {label}: "
        "síntomas, signos de alarma, dolor, fiebre y criterios de urgencia.",
    )
    return PROTOCOL_BASE_QUERIES + specific


def merge_retrieved_chunks(
    chunk_lists: list[list[RetrievedChunk]],
    *,
    max_chunks: int,
) -> list[RetrievedChunk]:
    """Merge multi-query results, keeping the highest score per chunk."""
    best_by_id: dict[str, RetrievedChunk] = {}
    for chunks in chunk_lists:
        for chunk in chunks:
            existing = best_by_id.get(chunk.chunk_id)
            if existing is None or chunk.score > existing.score:
                best_by_id[chunk.chunk_id] = chunk

    ranked = sorted(best_by_id.values(), key=lambda item: item.score, reverse=True)
    return ranked[:max_chunks]


def retrieve_protocol_context(
    retriever: ContextualRetriever,
    procedure_id: str,
    *,
    settings: Settings | None = None,
    top_k: int | None = None,
    score_threshold: float | None = None,
    per_query_top_k: int | None = None,
    expanded: bool = False,
) -> tuple[str, list[RetrievedChunk], float]:
    """Retrieve clinical evidence for protocol generation via multi-query RAG."""
    resolved = settings or get_settings()
    resolved_top_k = top_k if top_k is not None else resolved.protocol_retrieval_top_k

    if expanded:
        resolved_per_query_top_k = (
            per_query_top_k
            if per_query_top_k is not None
            else resolved.protocol_retrieval_expanded_per_query_top_k
        )
        resolved_score_threshold = (
            score_threshold
            if score_threshold is not None
            else resolved.protocol_retrieval_expanded_score_threshold
        )
    else:
        resolved_per_query_top_k = (
            per_query_top_k
            if per_query_top_k is not None
            else resolved.protocol_retrieval_per_query_top_k
        )
        resolved_score_threshold = (
            score_threshold
            if score_threshold is not None
            else resolved.protocol_retrieval_score_threshold
        )

    queries = protocol_queries_for(procedure_id)
    primary_query = queries[0]
    total_elapsed_ms = 0.0
    chunk_lists: list[list[RetrievedChunk]] = []

    for query in queries:
        _enriched_query, chunks, elapsed_ms = retriever.retrieve(
            query,
            procedure_id=procedure_id,
            postop_day=PROTOCOL_POSTOP_DAY,
            top_k=resolved_per_query_top_k,
            score_threshold=resolved_score_threshold,
        )
        total_elapsed_ms += elapsed_ms
        if chunks:
            chunk_lists.append(chunks)

    merged = merge_retrieved_chunks(chunk_lists, max_chunks=resolved_top_k)
    return primary_query, merged, total_elapsed_ms
