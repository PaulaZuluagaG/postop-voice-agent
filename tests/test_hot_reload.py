from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from api.services.documents import DocumentService
from api.services.procedure_classifier import ProcedureClassifier
from core.scenarios import list_procedure_folders


def test_list_procedure_folders_excludes_other(tmp_path: Path) -> None:
    (tmp_path / "appendicitis").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "hernia_repair").mkdir()

    folders = list_procedure_folders(tmp_path)

    assert "appendicitis" in folders
    assert "hernia_repair" in folders
    assert "other" not in folders


def test_procedure_classifier_suggest_procedure() -> None:
    settings = MagicMock()
    settings.textos_dir = Path("/tmp/textos")
    classifier = ProcedureClassifier(settings=settings)
    classifier._gemini = MagicMock()
    classifier._gemini.generate_json.return_value = {"suggested_procedure": "hernia_repair"}

    result = classifier.suggest_procedure(
        document_excerpt="Reparación de hernia laparoscópica postoperatoria.",
        existing_procedures=["appendicitis", "cholecystitis"],
    )

    assert result == "hernia_repair"


def test_confirm_document_reindexes_procedure(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.textos_dir = tmp_path / "textos"
    settings.protocol_dir = tmp_path / "protocol"
    service = DocumentService(settings=settings)
    service._pipeline = MagicMock()
    service._pipeline.reindex_procedure.return_value = MagicMock(total_chunks=3, errors=[])
    service._pipeline.store.list_sources.return_value = []

    temp_path = tmp_path / "pending.pdf"
    temp_path.write_bytes(b"%PDF-1.4")
    temp_id = "abc123"
    service._pending_uploads[temp_id] = temp_path

    item = service.confirm_document(
        temp_id=temp_id,
        procedure_id="appendicitis",
        file_name="guide.pdf",
    )

    service._pipeline.reindex_procedure.assert_called_once_with("appendicitis")
    assert item.file_name == "guide.pdf"
