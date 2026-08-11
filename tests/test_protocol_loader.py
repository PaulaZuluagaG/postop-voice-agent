from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from knowledge.protocol.loader import load_protocol_for_procedure
from knowledge.protocol.models import (
    PostOpProtocol,
    ProtocolThresholds,
    SymptomDefinition,
    SymptomLevel,
)


def _write_protocol(path: Path, procedure: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = PostOpProtocol(
        procedure=procedure,
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[
            SymptomDefinition(
                id="dolor",
                question="¿Cómo está su dolor?",
                type="numeric",
                levels=[SymptomLevel(min=0, max=10, points=1, label="verde")],
                fuentes=["doc_1"],
            )
        ],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=["dolor intenso"],
        source_ids=["doc_1"],
    )
    path.write_text(json.dumps(payload.model_dump(mode="json")), encoding="utf-8")


def test_load_protocol_uses_specific_when_present(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.protocol_dir = tmp_path
    _write_protocol(tmp_path / "appendicitis" / "protocol.json", "appendicitis")
    _write_protocol(tmp_path / "general" / "protocol.json", "general")

    protocol, key = load_protocol_for_procedure("appendicitis", settings=settings)

    assert protocol.procedure == "appendicitis"
    assert key == "appendicitis"


def test_load_protocol_falls_back_to_general_for_other(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.protocol_dir = tmp_path
    _write_protocol(tmp_path / "general" / "protocol.json", "general")

    protocol, key = load_protocol_for_procedure(
        "other", settings=settings, uses_general_protocol=True
    )

    assert protocol.procedure == "general"
    assert key == "general"


def test_load_protocol_falls_back_to_general_when_missing_specific(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.protocol_dir = tmp_path
    _write_protocol(tmp_path / "general" / "protocol.json", "general")

    protocol, key = load_protocol_for_procedure("hernia_repair", settings=settings)

    assert protocol.procedure == "general"
    assert key == "general"
