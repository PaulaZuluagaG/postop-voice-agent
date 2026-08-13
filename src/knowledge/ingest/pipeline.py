"""Batch ingestion pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from core.config import Settings, get_settings
from core.exceptions import InsufficientTextError
from core.models import IngestReport, ParsedDocument, ProcedureScenario
from core.scenarios import normalize_procedure_id
from knowledge.ingest.chunker import TokenChunker
from knowledge.ingest.embedder import EmbeddingService
from knowledge.ingest.pdf_parser import iter_pdf_files, parse_pdf
from knowledge.protocol.generator import (
    generate_protocol_for_procedure,
    generate_protocols_for_indexed_procedures,
)
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

        pdf_list = list(pdf_files)
        total_pdfs = len(pdf_list)
        logger.info("Starting ingest of %d PDF(s) from %s", total_pdfs, textos_dir)

        for index, pdf_path in enumerate(pdf_list, start=1):
            logger.info("[%d/%d] Processing %s", index, total_pdfs, pdf_path.name)
            try:
                document = parse_pdf(pdf_path, self._settings)
            except InsufficientTextError:
                report.skipped_no_text.append(str(pdf_path))
                logger.info(
                    "[%d/%d] Skipped insufficient text: %s", index, total_pdfs, pdf_path.name
                )
                continue
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{pdf_path.name}: {exc}")
                logger.exception("[%d/%d] Failed to parse %s", index, total_pdfs, pdf_path)
                continue

            if document.content_hash in seen_hashes:
                report.skipped_duplicates.append(str(pdf_path))
                logger.info("[%d/%d] Skipped duplicate: %s", index, total_pdfs, pdf_path.name)
                continue

            try:
                chunk_count = self._index_document(document)
                seen_hashes.add(document.content_hash)
                report.indexed_documents += 1
                logger.info(
                    "[%d/%d] Indexed %s (%d chunks, %d docs done)",
                    index,
                    total_pdfs,
                    pdf_path.name,
                    chunk_count,
                    report.indexed_documents,
                )
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{pdf_path.name}: {exc}")
                logger.exception("[%d/%d] Failed to index %s", index, total_pdfs, pdf_path)

        report.total_chunks = sum(source.chunk_count for source in self._store.list_sources())
        has_indexed_data = report.indexed_documents > 0 or self._store.list_indexed_procedure_ids()
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
        procedure_id: str | None = None,
    ) -> ParsedDocument:
        document = parse_pdf(
            file_path,
            self._settings,
            procedure_scenario=procedure_scenario,
        )
        if procedure_id is not None:
            document = document.model_copy(
                update={"procedure_id": normalize_procedure_id(procedure_id)}
            )
        self._store.create_collection(recreate=False)
        self._store.delete_document_chunks(document.source_id)
        self._index_document(document)
        return document

    def reindex_procedure(self, procedure_id: str) -> IngestReport:
        """Re-index all PDFs for a single procedure and regenerate its protocol."""
        procedure_id = normalize_procedure_id(procedure_id)
        report = IngestReport()
        self._store.delete_by_procedure(procedure_id)

        procedure_dir = self._settings.textos_dir / procedure_id
        if not procedure_dir.is_dir():
            report.errors.append(f"Procedure folder not found: {procedure_dir}")
            return report

        for pdf_path in sorted(procedure_dir.glob("*.pdf")):
            try:
                document = parse_pdf(pdf_path, self._settings)
                document = document.model_copy(update={"procedure_id": procedure_id})
                self._index_document(document)
                report.indexed_documents += 1
            except InsufficientTextError:
                report.skipped_no_text.append(str(pdf_path))
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{pdf_path.name}: {exc}")
                logger.exception("Failed to reindex %s", pdf_path)

        report.total_chunks = sum(
            source.chunk_count
            for source in self._store.list_sources()
            if source.procedure_id == procedure_id
        )
        if report.indexed_documents > 0:
            try:
                report.protocol_generation = generate_protocol_for_procedure(
                    procedure_id,
                    settings=self._settings,
                    store=self._store,
                    force=True,
                )
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"protocol:{procedure_id}: {exc}")
        return report

    def remove_document(self, source_id: str) -> None:
        self._store.delete_document_chunks(source_id)

    def _index_document(self, document: ParsedDocument) -> int:
        chunks = self._chunker.chunk_document(document)
        if not chunks:
            raise ValueError(f"No chunks produced for {document.file_name}")

        vectors = self._embedder.embed_chunks(chunks)
        self._store.delete_document_chunks(document.source_id)
        self._store.upsert_chunks(chunks, vectors, content_hash=document.content_hash)
        return len(chunks)
