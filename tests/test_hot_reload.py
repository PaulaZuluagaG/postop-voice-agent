from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from api.services.documents import DocumentService
from api.services.procedure_classifier import ProcedureClassifier, ProcedureSuggestionResult
from core.exceptions import DuplicateDocumentError
from core.procedure_labels import get_procedure_label, remove_procedure_label, save_procedure_label
from core.scenarios import list_procedure_folders


def test_list_procedure_folders_excludes_other(tmp_path: Path) -> None:
    appendicitis = tmp_path / "appendicitis"
    appendicitis.mkdir()
    (appendicitis / "guide.pdf").write_bytes(b"%PDF")
    (tmp_path / "other").mkdir()
    hernia = tmp_path / "hernia_repair"
    hernia.mkdir()
    (hernia / "guide.pdf").write_bytes(b"%PDF")
    empty = tmp_path / "removed-procedure"
    empty.mkdir()

    folders = list_procedure_folders(tmp_path)

    assert "appendicitis" in folders
    assert "hernia_repair" in folders
    assert "removed-procedure" not in folders
    assert "other" not in folders


def test_procedure_classifier_suggest_procedure() -> None:
    settings = MagicMock()
    settings.textos_dir = Path("/tmp/textos")
    classifier = ProcedureClassifier(settings=settings)
    classifier._gemini = MagicMock()
    classifier._gemini.generate_json.return_value = {
        "suggested_procedure": "hernia_repair",
        "procedure_label_es": "Reparación de hernia",
    }

    result = classifier.suggest_procedure(
        document_excerpt="Reparación de hernia laparoscópica postoperatoria.",
        existing_procedures=["appendicitis", "cholecystitis"],
    )

    assert result == ProcedureSuggestionResult(
        procedure_id="hernia_repair",
        label_es="Reparación de hernia",
    )


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


def test_confirm_document_saves_custom_procedure_label(tmp_path: Path) -> None:
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
    service._pending_labels[temp_id] = "Cirugía bariátrica"

    item = service.confirm_document(
        temp_id=temp_id,
        procedure_id="bariatric-surgery",
        file_name="guide.pdf",
        procedure_label="Cirugía bariátrica",
    )

    assert item.procedure_type == "Cirugía bariátrica"
    assert get_procedure_label(settings.textos_dir, "bariatric-surgery") == "Cirugía bariátrica"


def test_save_and_load_procedure_label(tmp_path: Path) -> None:
    save_procedure_label(tmp_path, "bariatric-surgery", "Cirugía bariátrica")
    assert get_procedure_label(tmp_path, "bariatric-surgery") == "Cirugía bariátrica"
    remove_procedure_label(tmp_path, "bariatric-surgery")
    assert get_procedure_label(tmp_path, "bariatric-surgery") is None


def test_delete_document_removes_custom_procedure_label(tmp_path: Path) -> None:
    settings = MagicMock()
    textos_dir = tmp_path / "textos"
    textos_dir.mkdir()
    settings.textos_dir = textos_dir
    settings.protocol_dir = tmp_path / "protocol"
    save_procedure_label(textos_dir, "bariatric-surgery", "Cirugía bariátrica")

    service = DocumentService(settings=settings)
    service._pipeline = MagicMock()
    service._pipeline.store.list_sources.side_effect = [
        [
            MagicMock(
                source_id="src_1",
                file_name="guide.pdf",
                procedure_id="bariatric-surgery",
                procedure_scenario=MagicMock(value="bariatric-surgery"),
            )
        ],
        [],
    ]

    service.delete_document("src_1")

    assert get_procedure_label(textos_dir, "bariatric-surgery") is None
    assert not (textos_dir / "bariatric-surgery").exists()


def test_upload_document_rejects_duplicate_pdf(tmp_path: Path) -> None:
    settings = MagicMock()
    textos_dir = tmp_path / "textos"
    appendicitis = textos_dir / "appendicitis"
    appendicitis.mkdir(parents=True)
    (appendicitis / "guide.pdf").write_bytes(b"%PDF-1.4 existing")
    settings.textos_dir = textos_dir
    settings.protocol_dir = tmp_path / "protocol"
    settings.document_validation_excerpt_chars = 1000

    service = DocumentService(settings=settings)
    service._validator = MagicMock()
    service._pipeline = MagicMock()

    with pytest.raises(DuplicateDocumentError, match="guide.pdf"):
        service.upload_document(
            file_name="guide.pdf",
            file_bytes=b"%PDF-1.4 new",
            procedure_id="appendicitis",
        )

    service._pipeline.reindex_procedure.assert_not_called()
