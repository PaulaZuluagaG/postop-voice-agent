"""Contextual retrieval for conversational turns."""

from __future__ import annotations

import time

from core.config import Settings, get_settings
from core.models import RetrievedChunk
from core.scenarios import FOLDER_TO_SCENARIO, procedure_display_label
from knowledge.ingest.embedder import EmbeddingService
from knowledge.store.qdrant_store import QdrantVectorStore


class ContextualRetriever:
    """Retrieve scenario-aware evidence for each patient turn."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: QdrantVectorStore | None = None,
        embedder: EmbeddingService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or QdrantVectorStore(self._settings)
        self._embedder = embedder or EmbeddingService(self._settings)

    @staticmethod
    def _procedure_label(procedure_key: str) -> str:
        scenario = FOLDER_TO_SCENARIO.get(procedure_key.lower())
        if scenario is not None:
            return scenario.value.replace("_", " ")
        return procedure_display_label(procedure_key)

    def build_enriched_query(
        self,
        patient_message: str,
        *,
        procedure_id: str,
        postop_day: int,
        conversation_context: str = "",
    ) -> str:
        parts = [
            f"Escenario: {self._procedure_label(procedure_id)}",
            f"Día postoperatorio: {postop_day}",
            f"Mensaje del paciente: {patient_message.strip()}",
        ]
        if conversation_context.strip():
            parts.append(f"Contexto previo: {conversation_context.strip()}")
        return "\n".join(parts)

    def retrieve(
        self,
        patient_message: str,
        *,
        procedure_id: str,
        postop_day: int,
        conversation_context: str = "",
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> tuple[str, list[RetrievedChunk], float]:
        start = time.perf_counter()
        query = self.build_enriched_query(
            patient_message,
            procedure_id=procedure_id,
            postop_day=postop_day,
            conversation_context=conversation_context,
        )
        query_vector = self._embedder.embed_texts([query])[0]
        hits = self._store.search(
            query_vector,
            procedure_scenario=procedure_id,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        retrieved = [RetrievedChunk(**chunk.model_dump(), score=score) for chunk, score in hits]
        elapsed_ms = (time.perf_counter() - start) * 1000
        return query, retrieved, elapsed_ms
