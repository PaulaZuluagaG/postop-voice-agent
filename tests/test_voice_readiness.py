"""Tests for voice readiness gating."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.config import Settings
from core.models import DocumentType, ProcedureScenario, SourceAggregate
from knowledge.protocol.generator import procedure_protocol_path, write_general_protocol
from knowledge.readiness import assess_voice_readiness


class FakeStore:
    def __init__(
        self,
        *,
        sources: list[SourceAggregate] | None = None,
        procedure_ids: list[str] | None = None,
    ) -> None:
        self._sources = sources or []
        self._procedure_ids = procedure_ids or []

    def list_sources(self) -> list[SourceAggregate]:
        return self._sources

    def list_indexed_procedure_ids(self) -> list[str]:
        return self._procedure_ids


def _settings(tmp_path: Path) -> Settings:
    textos = tmp_path / "textos"
    appendicitis = textos / "appendicitis"
    appendicitis.mkdir(parents=True)
    (appendicitis / "guide.pdf").write_bytes(b"%PDF")

    return Settings(
        textos_dir=textos,
        protocol_dir=tmp_path / "protocols",
    )


def _write_minimal_procedure_protocol(protocol_dir: Path, procedure_id: str) -> None:
    path = procedure_protocol_path(protocol_dir, procedure_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""{{
  "procedure": "{procedure_id}",
  "version": "1.0",
  "generated_at": "{datetime.now(tz=UTC).isoformat()}",
  "source_ids": ["src_test"],
  "symptoms": [
    {{
      "id": "pain",
      "question": "¿Tiene dolor?",
      "type": "binary",
      "levels": [
        {{"min": 0, "max": 0, "points": 0, "label": "verde"}},
        {{"min": 1, "max": 1, "points": 5, "label": "rojo"}}
      ],
      "fuentes": []
    }}
  ],
  "thresholds": {{"verde": 0, "amarillo": 8, "rojo": 15}},
  "alert_signs": [],
  "risk_factors": []
}}""",
        encoding="utf-8",
    )


def test_readiness_blocks_without_indexed_documents(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    result = assess_voice_readiness(settings, store=FakeStore())

    assert result.ready is False
    assert "documentos indexados" in result.detail.lower()


def test_readiness_blocks_without_general_protocol(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = FakeStore(
        sources=[
            SourceAggregate(
                source_id="s1",
                file_name="guide.pdf",
                procedure_id="appendicitis",
                procedure_scenario=ProcedureScenario.APPENDICITIS,
                document_type=DocumentType.GUIDE,
                language="es",
                chunk_count=3,
            )
        ],
        procedure_ids=["appendicitis"],
    )

    result = assess_voice_readiness(settings, store=store)

    assert result.ready is False
    assert "protocolos" in result.detail.lower()


def test_readiness_blocks_when_procedure_protocol_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    write_general_protocol(settings.protocol_dir)
    store = FakeStore(
        sources=[
            SourceAggregate(
                source_id="s1",
                file_name="guide.pdf",
                procedure_id="appendicitis",
                procedure_scenario=ProcedureScenario.APPENDICITIS,
                document_type=DocumentType.GUIDE,
                language="es",
                chunk_count=3,
            )
        ],
        procedure_ids=["appendicitis"],
    )

    result = assess_voice_readiness(settings, store=store)

    assert result.ready is False
    assert result.missing_protocols == ("appendicitis",)


def test_readiness_allows_when_documents_and_protocols_exist(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    write_general_protocol(settings.protocol_dir)
    _write_minimal_procedure_protocol(settings.protocol_dir, "appendicitis")
    store = FakeStore(
        sources=[
            SourceAggregate(
                source_id="s1",
                file_name="guide.pdf",
                procedure_id="appendicitis",
                procedure_scenario=ProcedureScenario.APPENDICITIS,
                document_type=DocumentType.GUIDE,
                language="es",
                chunk_count=3,
            )
        ],
        procedure_ids=["appendicitis"],
    )

    result = assess_voice_readiness(settings, store=store)

    assert result.ready is True
    assert result.indexed_documents == 1
    assert result.indexed_procedures == ("appendicitis",)
