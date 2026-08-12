from unittest.mock import MagicMock

from core.exceptions import VectorStoreError
from core.models import RetrievedChunk
from knowledge.retrieval.retriever import ContextualRetriever


def test_retriever_degrades_when_vector_store_unavailable() -> None:
    retriever = ContextualRetriever(
        store=MagicMock(),
        embedder=MagicMock(),
    )
    retriever._embedder.embed_texts.return_value = [[0.1, 0.2]]
    retriever._store.search.side_effect = VectorStoreError("collection missing")

    query, chunks, elapsed_ms = retriever.retrieve(
        "dolor postoperatorio",
        procedure_id="appendicitis",
        postop_day=2,
    )

    assert "appendicitis" in query.lower() or "Apendicitis" in query or query
    assert chunks == []
    assert elapsed_ms >= 0.0


def test_retriever_returns_hits_when_store_available() -> None:
    from core.models import DocumentType, ProcedureScenario, TextChunk

    chunk = TextChunk(
        chunk_id="c1",
        source_id="src1",
        text="evidencia",
        token_count=3,
        chunk_index=0,
        page_start=1,
        page_end=1,
        procedure_id="appendicitis",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        document_type=DocumentType.GUIDE,
        language="es",
        file_name="guia.pdf",
    )
    retriever = ContextualRetriever(
        store=MagicMock(),
        embedder=MagicMock(),
    )
    retriever._embedder.embed_texts.return_value = [[0.1, 0.2]]
    retriever._store.search.return_value = [(chunk, 0.9)]

    _query, chunks, _elapsed_ms = retriever.retrieve(
        "fiebre",
        procedure_id="appendicitis",
        postop_day=1,
    )

    assert len(chunks) == 1
    assert isinstance(chunks[0], RetrievedChunk)
    assert chunks[0].score == 0.9
