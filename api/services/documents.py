"""Document upload, listing, and deletion for the admin API."""

from __future__ import annotations

import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

from agent.llm.document_validator import DocumentValidator
from api.schemas import DocumentItem, ProcedureTypeOption
from core.config import Settings, get_settings
from core.exceptions import InsufficientTextError, PostOpError
from core.models import ProcedureScenario, SourceAggregate
from core.scenarios import SCENARIO_FOLDER_NAMES, SCENARIO_OPTIONS, scenario_label
from knowledge.ingest.pdf_parser import extract_document_excerpt
from knowledge.ingest.pipeline import IngestPipeline


class DocumentValidationError(PostOpError):
    """Document failed LLM category validation."""


class DocumentNotFoundError(PostOpError):
    """Requested source_id is not indexed."""


class DocumentService:
    """Orchestrates hot-reload ingest and Qdrant deletion."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._pipeline = IngestPipeline(self._settings)
        self._validator = DocumentValidator(self._settings)

    def list_procedure_types(self) -> list[ProcedureTypeOption]:
        options = [
            ProcedureTypeOption(value=scenario.value, label=label)
            for _key, label, scenario in SCENARIO_OPTIONS
        ]
        options.append(
            ProcedureTypeOption(value=ProcedureScenario.OTHER.value, label="Otro"),
        )
        return options

    def list_documents(self) -> list[DocumentItem]:
        sources = self._pipeline.store.list_sources()
        return [self._to_item(source) for source in sources]

    def upload_document(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        procedure_scenario: ProcedureScenario,
    ) -> DocumentItem:
        if not file_name.lower().endswith(".pdf"):
            raise ValueError("Solo se admiten archivos PDF.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / Path(file_name).name
            temp_path.write_bytes(file_bytes)

            excerpt = extract_document_excerpt(
                temp_path,
                max_chars=self._settings.document_validation_excerpt_chars,
            )
            if not excerpt:
                raise InsufficientTextError("El PDF no contiene texto suficiente para validar.")

            matches, message = self._validator.validate_document_category(
                document_excerpt=excerpt,
                procedure_scenario=procedure_scenario,
            )
            if not matches:
                raise DocumentValidationError(
                    message or "El documento no coincide con la categoría."
                )

            target_dir = self._settings.textos_dir / SCENARIO_FOLDER_NAMES[procedure_scenario]
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = target_dir / temp_path.name
            shutil.copy2(temp_path, destination)

        try:
            document = self._pipeline.index_document(
                destination,
                procedure_scenario=procedure_scenario,
            )
        except PostOpError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PostOpError(f"Error al indexar el documento: {exc}") from exc

        indexed = next(
            (
                source
                for source in self._pipeline.store.list_sources()
                if source.source_id == document.source_id
            ),
            None,
        )
        return DocumentItem(
            source_id=document.source_id,
            procedure_type=scenario_label(procedure_scenario),
            file_name=document.file_name,
            chunk_count=indexed.chunk_count if indexed else 0,
        )

    def delete_document(self, source_id: str) -> None:
        sources = {source.source_id: source for source in self._pipeline.store.list_sources()}
        if source_id not in sources:
            raise DocumentNotFoundError(f"Documento no encontrado: {source_id}")

        self._pipeline.remove_document(source_id)
        self._remove_pdf_from_disk(sources[source_id])

    def _remove_pdf_from_disk(self, source: SourceAggregate) -> None:
        if not source.file_name:
            return
        for pdf_path in self._settings.textos_dir.rglob("*.pdf"):
            if pdf_path.name == source.file_name:
                pdf_path.unlink(missing_ok=True)

    @staticmethod
    def _to_item(source: SourceAggregate) -> DocumentItem:
        return DocumentItem(
            source_id=source.source_id,
            procedure_type=scenario_label(source.procedure_scenario),
            file_name=source.file_name,
            chunk_count=source.chunk_count,
        )


@lru_cache
def get_document_service() -> DocumentService:
    return DocumentService()
