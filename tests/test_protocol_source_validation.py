from datetime import UTC, datetime

from core.models import DocumentType, ProcedureScenario, RetrievedChunk
from knowledge.protocol.gemini_client import ProtocolGeminiClient
from knowledge.protocol.models import (
    PostOpProtocol,
    ProtocolThresholds,
    RiskFactorDefinition,
    SymptomDefinition,
    SymptomLevel,
)


def _chunk(source_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-1",
        source_id=source_id,
        text="Pacientes con diabetes tipo 2 requieren vigilancia postoperatoria.",
        token_count=10,
        chunk_index=0,
        page_start=1,
        page_end=1,
        procedure_id="appendicitis",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        document_type=DocumentType.GUIDE,
        language="es",
        file_name="guide.pdf",
        score=0.9,
    )


def test_validate_protocol_sources_drops_risk_factors_without_valid_fuentes() -> None:
    protocol = PostOpProtocol(
        procedure="appendicitis",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[
            SymptomDefinition(
                id="dolor",
                question="¿Dolor?",
                type="numeric",
                levels=[SymptomLevel(min=0, max=3, points=0, label="verde")],
                fuentes=["src_real", "src_fake"],
            )
        ],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=[],
        risk_factors=[
            RiskFactorDefinition(
                id="diabetes_tipo_2",
                label="Diabetes tipo 2",
                fuentes=["src_real"],
            ),
            RiskFactorDefinition(
                id="consumo_de_tabaco",
                label="Consumo de tabaco",
                fuentes=["src_fake"],
            ),
        ],
    )

    validated = ProtocolGeminiClient._validate_protocol_sources(protocol, [_chunk("src_real")])

    assert validated.symptoms[0].fuentes == ["src_real"]
    assert len(validated.risk_factors) == 1
    assert validated.risk_factors[0].id == "diabetes_tipo_2"
