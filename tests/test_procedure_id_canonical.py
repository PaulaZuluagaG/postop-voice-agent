from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.scenarios import (
    canonical_procedure_id,
    legacy_protocol_directory_names,
    list_procedure_folders,
)
from knowledge.protocol.generator import write_procedure_protocol
from knowledge.protocol.models import (
    PostOpProtocol,
    ProtocolThresholds,
    SymptomDefinition,
    SymptomLevel,
)


def test_canonical_procedure_id_maps_enum_to_folder_slug() -> None:
    assert canonical_procedure_id("colorectal_cancer") == "colorectal-cancer"
    assert canonical_procedure_id("colorectal-cancer") == "colorectal-cancer"
    assert canonical_procedure_id("appendicitis") == "appendicitis"


def test_legacy_protocol_directory_names() -> None:
    assert legacy_protocol_directory_names("colorectal-cancer") == ["colorectal_cancer"]


def test_list_procedure_folders_deduplicates_aliases(tmp_path: Path) -> None:
    canonical = tmp_path / "colorectal-cancer"
    canonical.mkdir()
    (canonical / "guide.pdf").write_bytes(b"%PDF")
    (tmp_path / "colorectal cancer").mkdir()

    folders = list_procedure_folders(tmp_path)

    assert folders == ["colorectal-cancer"]


def test_write_procedure_protocol_removes_legacy_directory(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "colorectal_cancer"
    legacy_dir.mkdir()
    (legacy_dir / "protocol.json").write_text("{}", encoding="utf-8")

    protocol = PostOpProtocol(
        procedure="colorectal-cancer",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[
            SymptomDefinition(
                id="dolor",
                question="¿Dolor?",
                type="numeric",
                levels=[SymptomLevel(min=0, max=10, points=1, label="verde")],
                fuentes=["doc_1"],
            )
        ],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=["dolor intenso"],
        source_ids=["doc_1"],
    )

    destination = write_procedure_protocol(tmp_path, "colorectal_cancer", protocol)

    assert destination == tmp_path / "colorectal-cancer" / "protocol.json"
    assert destination.is_file()
    assert not legacy_dir.exists()
