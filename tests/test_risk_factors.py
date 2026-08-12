from __future__ import annotations

from datetime import UTC, datetime

from agent.decision.scoring import apply_risk_factor_bonus, resolve_severity
from core.models import SeverityLevel
from knowledge.protocol.models import (
    PostOpProtocol,
    ProtocolThresholds,
    RiskFactorDefinition,
    SymptomDefinition,
    SymptomLevel,
)


def _sample_protocol(*, risk_factors: list[RiskFactorDefinition] | None = None) -> PostOpProtocol:
    return PostOpProtocol(
        procedure="appendicitis",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[
            SymptomDefinition(
                id="dolor_abdominal",
                question="Del 0 al 10, ¿cómo califica su dolor?",
                type="numeric",
                levels=[SymptomLevel(min=4, max=7, points=4, label="amarillo")],
                fuentes=["doc_1"],
            )
        ],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=[],
        risk_factors=risk_factors or [],
        source_ids=["doc_1"],
    )


def test_apply_risk_factor_bonus_adds_constant_per_match() -> None:
    protocol = _sample_protocol(
        risk_factors=[
            RiskFactorDefinition(
                id="diabetes_tipo_2",
                label="Diabetes tipo 2",
                fuentes=["doc_1"],
            ),
            RiskFactorDefinition(id="obesidad", label="Obesidad", fuentes=["doc_1"]),
        ]
    )
    bonus, rules = apply_risk_factor_bonus(
        ["diabetes_tipo_2", "obesidad"],
        protocol.risk_factors,
        bonus_per_match=2,
    )
    assert bonus == 4
    assert len(rules) == 2


def test_apply_risk_factor_bonus_ignores_non_matching_comorbidities() -> None:
    protocol = _sample_protocol(
        risk_factors=[
            RiskFactorDefinition(id="diabetes_tipo_2", label="Diabetes tipo 2", fuentes=["doc_1"])
        ]
    )
    bonus, rules = apply_risk_factor_bonus(
        ["hipertension"],
        protocol.risk_factors,
        bonus_per_match=2,
    )
    assert bonus == 0
    assert rules == []


def test_post_op_protocol_caps_risk_factors_from_llm_output() -> None:
    protocol = PostOpProtocol.from_llm_output(
        {
            "procedure": "appendicitis",
            "symptoms": [],
            "thresholds": {"verde": 0, "amarillo": 8, "rojo": 15},
            "alert_signs": [],
            "risk_factors": [
                {"id": "diabetes_tipo_2", "label": "Diabetes tipo 2", "fuentes": ["doc_1"]},
                {"id": "obesidad", "label": "Obesidad", "fuentes": ["doc_2"]},
                {"id": "epoc", "label": "EPOC", "fuentes": ["doc_3"]},
            ],
        },
        source_ids=["doc_1"],
    )
    assert len(protocol.risk_factors) == 2


def test_resolve_severity_after_risk_bonus() -> None:
    protocol = _sample_protocol()
    bonus, _ = apply_risk_factor_bonus(
        ["diabetes_tipo_2"],
        [RiskFactorDefinition(id="diabetes_tipo_2", label="Diabetes tipo 2", fuentes=["doc_1"])],
        bonus_per_match=2,
    )
    cumulative = 7 + bonus
    assert resolve_severity(cumulative, protocol.thresholds) == SeverityLevel.YELLOW
