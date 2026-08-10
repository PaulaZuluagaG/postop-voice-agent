"""Batch ingestion pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from core.config import Settings, get_settings
from core.exceptions import InsufficientTextError
from core.models import IngestReport, ParsedDocument, ProcedureScenario
from knowledge.ingest.chunker import TokenChunker
from knowledge.ingest.embedder import EmbeddingService
from knowledge.ingest.pdf_parser import iter_pdf_files, parse_pdf
from knowledge.protocol.generator import generate_protocols_for_indexed_procedures
from knowledge.store.qdrant_store import QdrantVectorStore

logger = logging.getLogger(__name__)


class IngestPipeline:
    """Parse PDFs, deduplicate, chunk, embed, and upsert into Qdrant."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._chunker = TokenChunker(self._settings)
        self._embedder = EmbeddingService(self._settings)
        self._store = QdrantVectorStore(self._settings)

    @property
    def store(self) -> QdrantVectorStore:
        return self._store

    def ingest_directory(
        self,
        textos_dir: Path | None = None,
        *,
        recreate: bool = False,
        generate_protocols: bool = True,
    ) -> IngestReport:
        textos_dir = textos_dir or self._settings.textos_dir
        report = IngestReport()

        if recreate:
            self._store.delete_and_recreate()
        else:
            self._store.create_collection(recreate=False)

        seen_hashes: set[str] = set(self._store.get_indexed_hashes())
        pdf_files = iter_pdf_files(textos_dir)

        for pdf_path in pdf_files:
            try:
                document = parse_pdf(pdf_path, self._settings)
            except InsufficientTextError:
                report.skipped_no_text.append(str(pdf_path))
                logger.info("Skipped insufficient text: %s", pdf_path.name)
                continue
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{pdf_path.name}: {exc}")
                logger.exception("Failed to parse %s", pdf_path)
                continue

            if document.content_hash in seen_hashes:
                report.skipped_duplicates.append(str(pdf_path))
                logger.info("Skipped duplicate: %s", pdf_path.name)
                continue

            try:
                self._index_document(document)
                seen_hashes.add(document.content_hash)
                report.indexed_documents += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{pdf_path.name}: {exc}")
                logger.exception("Failed to index %s", pdf_path)

        report.total_chunks = sum(source.chunk_count for source in self._store.list_sources())
        has_indexed_data = report.indexed_documents > 0 or self._store.list_indexed_scenarios()
        if generate_protocols and has_indexed_data:
            report.protocol_generation = generate_protocols_for_indexed_procedures(
                settings=self._settings,
                store=self._store,
            )
        return report

    def generate_protocols(self, *, force: bool = False) -> IngestReport:
        """Generate protocols for all indexed procedures without re-ingesting PDFs."""
        report = IngestReport()
        report.protocol_generation = generate_protocols_for_indexed_procedures(
            settings=self._settings,
            store=self._store,
            force=force,
        )
        return report

    def index_document(
        self,
        file_path: Path,
        *,
        procedure_scenario: ProcedureScenario | None = None,
    ) -> ParsedDocument:
        document = parse_pdf(
            file_path,
            self._settings,
            procedure_scenario=procedure_scenario,
        )
        self._store.create_collection(recreate=False)
        self._store.delete_document_chunks(document.source_id)
        self._index_document(document)
        return document

    def remove_document(self, source_id: str) -> None:
        self._store.delete_document_chunks(source_id)

    def _index_document(self, document: ParsedDocument) -> None:
        chunks = self._chunker.chunk_document(document)
        if not chunks:
            raise ValueError(f"No chunks produced for {document.file_name}")

        vectors = self._embedder.embed_chunks(chunks)
        self._store.delete_document_chunks(document.source_id)
        self._store.upsert_chunks(chunks, vectors, content_hash=document.content_hash)
