"""Document upload, listing, and deletion for the admin API."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

from agent.llm.document_validator import DocumentValidator
from api.schemas import DocumentItem, ProcedureSuggestion, ProcedureTypeOption
from api.services.procedure_classifier import ProcedureClassifier
from core.config import Settings, get_settings
from core.exceptions import DuplicateDocumentError, InsufficientTextError, PostOpError
from core.models import SourceAggregate
from core.procedure_labels import remove_procedure_label, save_procedure_label
from core.scenarios import (
    FOLDER_TO_SCENARIO,
    OTHER_OPTION_VALUE,
    canonical_procedure_id,
    is_valid_procedure_id,
    list_admin_procedure_options,
    normalize_procedure_id,
    procedure_display_label,
)
from knowledge.ingest.pdf_parser import extract_document_excerpt
from knowledge.ingest.pipeline import IngestPipeline
from knowledge.protocol.generator import (
    _remove_legacy_protocol_dirs,
    procedure_protocol_path,
)


class DocumentValidationError(PostOpError):
    """Document failed LLM category validation."""


class DocumentNotFoundError(PostOpError):
    """Requested source_id is not indexed."""


class PendingUploadNotFoundError(PostOpError):
    """Temporary upload id not found."""


class DocumentService:
    """Orchestrates hot-reload ingest and Qdrant deletion."""

    _pending_uploads: dict[str, Path] = {}
    _pending_labels: dict[str, str] = {}

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._pipeline = IngestPipeline(self._settings)
        self._validator = DocumentValidator(self._settings)
        self._classifier = ProcedureClassifier(self._settings)

    def list_procedure_types(self) -> list[ProcedureTypeOption]:
        return [
            ProcedureTypeOption(value=value, label=label)
            for value, label in list_admin_procedure_options(self._settings.textos_dir)
        ]

    def list_documents(self) -> list[DocumentItem]:
        sources = self._pipeline.store.list_sources()
        return [self._to_item(source) for source in sources]

    def analyze_document(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
    ) -> ProcedureSuggestion:
        self._ensure_pdf_not_duplicate(file_name)
        temp_path = self._write_temp_pdf(file_name, file_bytes)
        excerpt = extract_document_excerpt(
            temp_path,
            max_chars=self._settings.document_validation_excerpt_chars,
        )
        if not excerpt:
            temp_path.unlink(missing_ok=True)
            raise InsufficientTextError("El PDF no contiene texto suficiente para clasificar.")

        suggested = self._classifier.suggest_procedure(document_excerpt=excerpt)
        normalized = suggested.procedure_id
        if not is_valid_procedure_id(normalized):
            raise ValueError(
                f"El clasificador devolvió un procedure inválido: {normalized!r}. "
                "Corrígelo manualmente en el modal."
            )
        temp_id = uuid.uuid4().hex
        self._pending_uploads[temp_id] = temp_path
        self._pending_labels[temp_id] = suggested.label_es
        return ProcedureSuggestion(
            suggested_procedure=normalized,
            suggested_procedure_label=suggested.label_es,
            temp_id=temp_id,
        )

    def confirm_document(
        self,
        *,
        temp_id: str,
        procedure_id: str,
        file_name: str,
        procedure_label: str | None = None,
    ) -> DocumentItem:
        temp_path = self._pending_uploads.pop(temp_id, None)
        pending_label = self._pending_labels.pop(temp_id, "")
        if temp_path is None or not temp_path.is_file():
            raise PendingUploadNotFoundError(f"Carga pendiente no encontrada: {temp_id}")

        normalized_procedure = canonical_procedure_id(procedure_id)
        if not is_valid_procedure_id(normalized_procedure):
            raise ValueError(f"Procedure inválido: {procedure_id}")

        label_es = (procedure_label or pending_label or "").strip()
        if label_es and normalized_procedure not in FOLDER_TO_SCENARIO:
            save_procedure_label(self._settings.textos_dir, normalized_procedure, label_es)

        self._ensure_pdf_not_duplicate(file_name, normalized_procedure)

        target_dir = self._settings.textos_dir / normalized_procedure
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / Path(file_name).name
        shutil.copy2(temp_path, destination)
        temp_path.unlink(missing_ok=True)

        report = self._pipeline.reindex_procedure(normalized_procedure)
        if report.errors:
            raise PostOpError("; ".join(report.errors))

        indexed = next(
            (
                source
                for source in self._pipeline.store.list_sources()
                if source.file_name == destination.name
            ),
            None,
        )
        return DocumentItem(
            source_id=indexed.source_id if indexed else "",
            procedure_type=procedure_display_label(
                normalized_procedure,
                textos_dir=self._settings.textos_dir,
            ),
            file_name=destination.name,
            chunk_count=indexed.chunk_count if indexed else report.total_chunks,
        )

    def upload_document(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        procedure_id: str,
    ) -> DocumentItem:
        normalized = normalize_procedure_id(procedure_id)
        if normalized == OTHER_OPTION_VALUE:
            raise ValueError("Use /admin/documents/analyze y /admin/documents/confirm para Otro.")

        self._ensure_pdf_not_duplicate(file_name, normalized)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / Path(file_name).name
            temp_path.write_bytes(file_bytes)

            excerpt = extract_document_excerpt(
                temp_path,
                max_chars=self._settings.document_validation_excerpt_chars,
            )
            if not excerpt:
                raise InsufficientTextError("El PDF no contiene texto suficiente para validar.")

            target_dir = self._settings.textos_dir / normalized
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = target_dir / temp_path.name
            shutil.copy2(temp_path, destination)

        report = self._pipeline.reindex_procedure(normalized)
        if report.errors:
            raise PostOpError("; ".join(report.errors))

        indexed = next(
            (
                source
                for source in self._pipeline.store.list_sources()
                if source.file_name == destination.name
            ),
            None,
        )
        return DocumentItem(
            source_id=indexed.source_id if indexed else "",
            procedure_type=procedure_display_label(
                normalized,
                textos_dir=self._settings.textos_dir,
            ),
            file_name=destination.name,
            chunk_count=indexed.chunk_count if indexed else report.total_chunks,
        )

    def delete_document(self, source_id: str) -> None:
        sources = {source.source_id: source for source in self._pipeline.store.list_sources()}
        if source_id not in sources:
            raise DocumentNotFoundError(f"Documento no encontrado: {source_id}")

        source = sources[source_id]
        procedure_id = canonical_procedure_id(
            source.procedure_id or source.procedure_scenario.value
        )
        self._pipeline.remove_document(source_id)
        self._remove_pdf_from_disk(source)

        remaining = [
            item
            for item in self._pipeline.store.list_sources()
            if (item.procedure_id or item.procedure_scenario.value)
            in {
                procedure_id,
                source.procedure_scenario.value,
            }
        ]
        if remaining:
            self._pipeline.reindex_procedure(procedure_id)
            return

        procedure_dir = self._settings.textos_dir / procedure_id
        if procedure_dir.is_dir():
            shutil.rmtree(procedure_dir, ignore_errors=True)
        remove_procedure_label(self._settings.textos_dir, procedure_id)
        protocol_path = procedure_protocol_path(self._settings.protocol_dir, procedure_id)
        if protocol_path.is_file():
            protocol_path.unlink(missing_ok=True)
        if protocol_path.parent.is_dir() and not any(protocol_path.parent.iterdir()):
            protocol_path.parent.rmdir()
        _remove_legacy_protocol_dirs(self._settings.protocol_dir, procedure_id)
        self._pipeline.store.delete_by_procedure(procedure_id)

    def _write_temp_pdf(self, file_name: str, file_bytes: bytes) -> Path:
        if not file_name.lower().endswith(".pdf"):
            raise ValueError("Solo se admiten archivos PDF.")
        temp_dir = Path(tempfile.mkdtemp(prefix="postop_upload_"))
        temp_path = temp_dir / Path(file_name).name
        temp_path.write_bytes(file_bytes)
        return temp_path

    def _find_existing_pdf(self, file_name: str) -> Path | None:
        clean_name = Path(file_name).name
        if not clean_name:
            return None
        for pdf_path in self._settings.textos_dir.rglob("*.pdf"):
            if pdf_path.name == clean_name:
                return pdf_path
        return None

    def _ensure_pdf_not_duplicate(self, file_name: str, procedure_id: str | None = None) -> None:
        existing = self._find_existing_pdf(file_name)
        if existing is None:
            return
        rel = existing.relative_to(self._settings.textos_dir)
        procedure_folder = rel.parts[0] if rel.parts else rel.as_posix()
        if procedure_id and canonical_procedure_id(procedure_id) == canonical_procedure_id(
            procedure_folder
        ):
            raise DuplicateDocumentError(
                f"El documento {Path(file_name).name} ya existe en "
                f"data/textos/{procedure_folder}/."
            )
        raise DuplicateDocumentError(
            f"El documento {Path(file_name).name} ya existe en data/textos/{rel.parent}."
        )

    def _remove_pdf_from_disk(self, source: SourceAggregate) -> None:
        if not source.file_name:
            return
        for pdf_path in self._settings.textos_dir.rglob("*.pdf"):
            if pdf_path.name == source.file_name:
                pdf_path.unlink(missing_ok=True)

    def _to_item(self, source: SourceAggregate) -> DocumentItem:
        procedure_id = canonical_procedure_id(
            source.procedure_id or source.procedure_scenario.value
        )
        return DocumentItem(
            source_id=source.source_id,
            procedure_type=procedure_display_label(
                procedure_id,
                textos_dir=self._settings.textos_dir,
            ),
            file_name=source.file_name,
            chunk_count=source.chunk_count,
        )


@lru_cache
def get_document_service() -> DocumentService:
    return DocumentService()
