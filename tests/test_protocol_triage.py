from __future__ import annotations

from datetime import UTC, datetime

from agent.decision.protocol_triage import (
    extract_symptom_values,
    pending_symptoms,
    update_covered_symptoms,
)
from core.models import ClinicalFacts, LLMTurnOutput, ResponseCategory
from knowledge.protocol.models import (
    PostOpProtocol,
    ProtocolThresholds,
    SymptomDefinition,
    SymptomLevel,
)


def _sample_protocol() -> PostOpProtocol:
    return PostOpProtocol(
        procedure="appendicitis",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[
            SymptomDefinition(
                id="dolor_abdominal",
                question="Del 0 al 10, ¿cómo califica su dolor?",
                type="numeric",
                levels=[SymptomLevel(min=0, max=3, points=0, label="verde")],
                fuentes=["doc_1"],
            ),
            SymptomDefinition(
                id="fiebre",
                question="¿Ha tenido fiebre?",
                type="binary",
                levels=[SymptomLevel(min=0, max=1, points=5, label="amarillo")],
                fuentes=["doc_1"],
            ),
        ],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=["dolor intenso"],
        source_ids=["doc_1"],
    )


def test_pending_symptoms_excludes_covered() -> None:
    protocol = _sample_protocol()
    pending = pending_symptoms(protocol, {"dolor_abdominal"})
    assert [symptom.id for symptom in pending] == ["fiebre"]


def test_update_covered_symptoms_from_llm_output() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        hechos=ClinicalFacts(),
        sintomas={"fiebre": True},
        foco_sintoma="fiebre",
        texto_paciente="Entiendo.",
    )
    covered = update_covered_symptoms(set(), llm_output)
    assert "fiebre" in covered


def test_extract_symptom_values_merges_llm_sintomas() -> None:
    llm_output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        hechos=ClinicalFacts(dolor_0_10=7),
        sintomas={"dolor_abdominal": 7},
        foco_sintoma="dolor_abdominal",
        texto_paciente="Entiendo.",
    )
    values = extract_symptom_values(llm_output)
    assert values["dolor_abdominal"] == 7
