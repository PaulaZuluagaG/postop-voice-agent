"""Qdrant vector store operations."""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from core.config import Settings, get_settings
from core.exceptions import VectorStoreError
from core.models import DocumentType, ProcedureScenario, SourceAggregate, TextChunk
from core.retry import with_retry
from core.scenarios import canonical_procedure_id, qdrant_filter_values

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """Vector store backed by Qdrant with retry on transient failures."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = QdrantClient(
            url=self._settings.qdrant_url,
            timeout=self._settings.qdrant_timeout_seconds,
        )

    @property
    def collection_name(self) -> str:
        return self._settings.qdrant_collection

    def _run(self, operation_name: str, fn):
        try:
            return with_retry(fn, operation_name=operation_name)
        except Exception as exc:  # noqa: BLE001
            raise VectorStoreError(f"{operation_name} failed: {exc}") from exc

    def collection_exists(self) -> bool:
        def _check() -> bool:
            collections = self._client.get_collections().collections
            return any(item.name == self.collection_name for item in collections)

        return self._run("collection_exists", _check)

    def create_collection(self, *, recreate: bool = False) -> None:
        def _create() -> None:
            if recreate and self.collection_exists():
                self._client.delete_collection(self.collection_name)
            if not self.collection_exists():
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self._settings.embedding_dimension,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
                self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="source_id",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
                self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="procedure_scenario",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
                self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="content_hash",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )

        self._run("create_collection", _create)

    def delete_and_recreate(self) -> None:
        self.create_collection(recreate=True)

    def delete_document_chunks(self, source_id: str) -> None:
        def _delete() -> None:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="source_id",
                                match=qmodels.MatchValue(value=source_id),
                            )
                        ]
                    )
                ),
            )

        self._run("delete_document_chunks", _delete)

    def delete_by_content_hash(self, content_hash: str) -> None:
        def _delete() -> None:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="content_hash",
                                match=qmodels.MatchValue(value=content_hash),
                            )
                        ]
                    )
                ),
            )

        self._run("delete_by_content_hash", _delete)

    def delete_by_procedure(self, procedure_id: str) -> None:
        filter_values = qdrant_filter_values(canonical_procedure_id(procedure_id))

        def _delete() -> None:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        should=[
                            qmodels.FieldCondition(
                                key="procedure_id",
                                match=qmodels.MatchValue(value=value),
                            )
                            for value in filter_values
                        ]
                        + [
                            qmodels.FieldCondition(
                                key="procedure_scenario",
                                match=qmodels.MatchValue(value=value),
                            )
                            for value in filter_values
                        ]
                    )
                ),
            )

        self._run("delete_by_procedure", _delete)

    def upsert_chunks(
        self,
        chunks: list[TextChunk],
        vectors: list[list[float]],
        *,
        content_hash: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise VectorStoreError("Chunk and vector counts must match")
        if not chunks:
            return

        points = [
            qmodels.PointStruct(
                id=chunk.chunk_id,
                vector=vector,
                payload=self._chunk_payload(chunk, content_hash),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

        def _upsert() -> None:
            self._client.upsert(collection_name=self.collection_name, points=points)

        self._run("upsert_chunks", _upsert)

    def search(
        self,
        query_vector: list[float],
        *,
        procedure_scenario: str,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list[tuple[TextChunk, float]]:
        top_k = top_k or self._settings.retrieval_top_k
        score_threshold = score_threshold or self._settings.retrieval_score_threshold

        filter_values = qdrant_filter_values(procedure_scenario)
        scenario_filter = qmodels.Filter(
            should=[
                qmodels.FieldCondition(
                    key="procedure_id",
                    match=qmodels.MatchValue(value=value),
                )
                for value in filter_values
            ]
            + [
                qmodels.FieldCondition(
                    key="procedure_scenario",
                    match=qmodels.MatchValue(value=value),
                )
                for value in filter_values
            ]
        )

        def _search():
            response = self._client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=scenario_filter,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
            )
            return response.points

        hits = self._run("search", _search)
        results: list[tuple[TextChunk, float]] = []
        for hit in hits:
            payload = hit.payload or {}
            chunk = TextChunk(
                chunk_id=str(hit.id),
                source_id=str(payload.get("source_id", "")),
                text=str(payload.get("text", "")),
                token_count=int(payload.get("token_count", 0)),
                chunk_index=int(payload.get("chunk_index", 0)),
                page_start=int(payload.get("page_start", 0)),
                page_end=int(payload.get("page_end", 0)),
                procedure_id=str(
                    payload.get("procedure_id", payload.get("procedure_scenario", ""))
                ),
                procedure_scenario=ProcedureScenario(
                    str(payload.get("procedure_scenario", ProcedureScenario.OTHER.value))
                ),
                document_type=DocumentType(
                    str(payload.get("document_type", DocumentType.OTHER.value))
                ),
                language=str(payload.get("language", "es")),
                file_name=str(payload.get("file_name", "")),
            )
            results.append((chunk, float(hit.score or 0.0)))
        return results

    def list_sources(self) -> list[SourceAggregate]:
        def _scroll() -> list[SourceAggregate]:
            aggregates: dict[str, SourceAggregate] = {}
            offset = None
            while True:
                points, offset = self._client.scroll(
                    collection_name=self.collection_name,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    source_id = str(payload.get("source_id", ""))
                    if not source_id:
                        continue
                    if source_id not in aggregates:
                        aggregates[source_id] = SourceAggregate(
                            source_id=source_id,
                            file_name=str(payload.get("file_name", "")),
                            procedure_id=str(
                                payload.get(
                                    "procedure_id",
                                    payload.get("procedure_scenario", ""),
                                )
                            ),
                            procedure_scenario=ProcedureScenario(
                                str(
                                    payload.get("procedure_scenario", ProcedureScenario.OTHER.value)
                                )
                            ),
                            document_type=DocumentType(
                                str(payload.get("document_type", DocumentType.OTHER.value))
                            ),
                            language=str(payload.get("language", "es")),
                            chunk_count=0,
                        )
                    aggregates[source_id].chunk_count += 1
                if offset is None:
                    break
            return sorted(aggregates.values(), key=lambda item: item.file_name.lower())

        return self._run("list_sources", _scroll)

    def get_source_content_hashes(self, procedure_id: str) -> dict[str, str]:
        """Map indexed source_id -> content_hash for one procedure."""

        def _scroll() -> dict[str, str]:
            filter_values = qdrant_filter_values(canonical_procedure_id(procedure_id))
            procedure_filter = qmodels.Filter(
                should=[
                    qmodels.FieldCondition(
                        key="procedure_id",
                        match=qmodels.MatchValue(value=value),
                    )
                    for value in filter_values
                ]
                + [
                    qmodels.FieldCondition(
                        key="procedure_scenario",
                        match=qmodels.MatchValue(value=value),
                    )
                    for value in filter_values
                ]
            )
            hashes: dict[str, str] = {}
            offset = None
            while True:
                points, offset = self._client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=procedure_filter,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    source_id = payload.get("source_id")
                    content_hash = payload.get("content_hash")
                    if not source_id or not content_hash:
                        continue
                    source_key = str(source_id)
                    if source_key not in hashes:
                        hashes[source_key] = str(content_hash)
                if offset is None:
                    break
            return hashes

        return self._run("get_source_content_hashes", _scroll)

    def list_indexed_procedure_ids(self) -> list[str]:
        def _scroll() -> list[str]:
            procedure_ids: set[str] = set()
            offset = None
            while True:
                points, offset = self._client.scroll(
                    collection_name=self.collection_name,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    raw = payload.get("procedure_id") or payload.get("procedure_scenario")
                    if raw:
                        procedure_ids.add(canonical_procedure_id(str(raw)))
                if offset is None:
                    break
            return sorted(procedure_ids)

        return self._run("list_indexed_procedure_ids", _scroll)

    def list_indexed_scenarios(self) -> list[ProcedureScenario]:
        def _scroll() -> list[ProcedureScenario]:
            scenarios: set[ProcedureScenario] = set()
            offset = None
            while True:
                points, offset = self._client.scroll(
                    collection_name=self.collection_name,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    raw = payload.get("procedure_scenario")
                    if not raw:
                        continue
                    scenarios.add(ProcedureScenario(str(raw)))
                if offset is None:
                    break
            return sorted(scenarios, key=lambda item: item.value)

        return self._run("list_indexed_scenarios", _scroll)

    def set_protocol_payload(
        self,
        procedure_id: str,
        protocol: dict[str, Any],
    ) -> int:
        filter_values = qdrant_filter_values(canonical_procedure_id(procedure_id))

        def _set_payload() -> int:
            scenario_filter = qmodels.Filter(
                should=[
                    qmodels.FieldCondition(
                        key="procedure_id",
                        match=qmodels.MatchValue(value=value),
                    )
                    for value in filter_values
                ]
                + [
                    qmodels.FieldCondition(
                        key="procedure_scenario",
                        match=qmodels.MatchValue(value=value),
                    )
                    for value in filter_values
                ]
            )
            self._client.set_payload(
                collection_name=self.collection_name,
                payload={"protocol": protocol},
                points=scenario_filter,
                wait=True,
            )
            return self._count_points(scenario_filter)

        return self._run("set_protocol_payload", _set_payload)

    def _count_points(self, scenario_filter: qmodels.Filter) -> int:
        result = self._client.count(
            collection_name=self.collection_name,
            count_filter=scenario_filter,
            exact=True,
        )
        return int(result.count)

    def get_indexed_hashes(self) -> set[str]:
        hashes: set[str] = set()
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                content_hash = payload.get("content_hash")
                if content_hash:
                    hashes.add(str(content_hash))
            if offset is None:
                break
        return hashes

    @staticmethod
    def _chunk_payload(chunk: TextChunk, content_hash: str) -> dict[str, Any]:
        return {
            "source_id": chunk.source_id,
            "text": chunk.text,
            "token_count": chunk.token_count,
            "chunk_index": chunk.chunk_index,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "procedure_id": chunk.procedure_id,
            "procedure_scenario": chunk.procedure_scenario.value
            if hasattr(chunk.procedure_scenario, "value")
            else str(chunk.procedure_scenario),
            "document_type": chunk.document_type.value
            if hasattr(chunk.document_type, "value")
            else str(chunk.document_type),
            "language": chunk.language,
            "file_name": chunk.file_name,
            "content_hash": content_hash,
        }
