from datetime import UTC, datetime
from pathlib import Path

from knowledge.protocol.loader import list_risk_factors_for_procedure, load_protocol_for_procedure
from knowledge.protocol.models import (
    PostOpProtocol,
    ProtocolThresholds,
    RiskFactorDefinition,
    SymptomDefinition,
    SymptomLevel,
)


def _write_protocol(path: Path, *, risk_factors: list[dict[str, str]] | None = None) -> None:
    protocol = PostOpProtocol(
        procedure="appendicitis",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[
            SymptomDefinition(
                id="dolor_abdominal",
                question="Del 0 al 10, ¿cómo califica su dolor?",
                type="numeric",
                levels=[SymptomLevel(min=0, max=3, points=0, label="verde")],
                fuentes=["doc_1"],
            )
        ],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=[],
        risk_factors=[RiskFactorDefinition.model_validate(item) for item in (risk_factors or [])],
        source_ids=["doc_1"],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(protocol.model_dump_json(indent=2), encoding="utf-8")


def test_list_risk_factors_for_procedure_returns_protocol_options(tmp_path: Path) -> None:
    from core.config import Settings

    protocol_dir = tmp_path / "protocol"
    _write_protocol(
        protocol_dir / "appendicitis" / "protocol.json",
        risk_factors=[
            {"id": "diabetes_tipo_2", "label": "Diabetes tipo 2", "fuentes": ["doc_1"]},
            {"id": "obesidad", "label": "Obesidad", "fuentes": ["doc_1"]},
        ],
    )
    _write_protocol(protocol_dir / "general" / "protocol.json")

    settings = Settings(protocol_dir=protocol_dir)
    factors = list_risk_factors_for_procedure("appendicitis", settings=settings)
    assert factors == [
        {"id": "diabetes_tipo_2", "label": "Diabetes tipo 2"},
        {"id": "obesidad", "label": "Obesidad"},
    ]


def test_list_risk_factors_for_other_returns_empty(tmp_path: Path) -> None:
    from core.config import Settings

    protocol_dir = tmp_path / "protocol"
    _write_protocol(protocol_dir / "general" / "protocol.json")
    settings = Settings(protocol_dir=protocol_dir)

    assert (
        list_risk_factors_for_procedure("other", settings=settings, uses_general_protocol=True)
        == []
    )


def test_load_protocol_without_risk_factors_defaults_to_empty(tmp_path: Path) -> None:
    from core.config import Settings

    protocol_dir = tmp_path / "protocol"
    _write_protocol(protocol_dir / "appendicitis" / "protocol.json")
    _write_protocol(protocol_dir / "general" / "protocol.json")
    settings = Settings(protocol_dir=protocol_dir)

    protocol, _ = load_protocol_for_procedure("appendicitis", settings=settings)
    assert protocol.risk_factors == []
