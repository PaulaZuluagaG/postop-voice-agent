from uuid import uuid4

from agent.decision.clinical_summary import (
    build_clinical_summary,
    build_next_steps,
    consolidate_symptoms_reported,
    format_sources_used_text,
    format_symptoms_reported_text,
    replace_clinical_summary_sources,
    resolve_call_triage,
)
from core.models import CallSessionState, CallSummary, ProcedureScenario, SeverityLevel, TurnRecord


def _session_with_turns() -> CallSessionState:
    return CallSessionState(
        call_id=uuid4(),
        procedure_id="appendicitis",
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        postop_day=3,
        patient_name="Ana López",
        patient_id="PAC-101",
        protocol_symptoms=[
            {"id": "fiebre", "question": "¿Ha tenido fiebre?"},
            {"id": "dolor", "question": "¿Cómo califica su dolor?"},
        ],
        turns=[
            TurnRecord(
                turn_number=1,
                patient_input="Tengo fiebre",
                agent_response="¿Cuál es su temperatura?",
                rag_query="fiebre",
                symptoms={"fiebre": 38.2},
            ),
            TurnRecord(
                turn_number=2,
                patient_input="Duele bastante",
                agent_response="¿Del 0 al 10?",
                rag_query="dolor",
                symptoms={"dolor": 7},
            ),
        ],
        cumulative_score=9,
        current_severity=SeverityLevel.YELLOW,
    )


def test_consolidate_symptoms_reported_uses_latest_value() -> None:
    session = _session_with_turns()
    session.turns[0].symptoms["dolor"] = 4

    merged = consolidate_symptoms_reported(session)

    assert merged["fiebre"] == 38.2
    assert merged["dolor"] == 7


def test_build_clinical_summary_without_llm() -> None:
    session = _session_with_turns()
    symptoms_reported = consolidate_symptoms_reported(session)
    next_steps = build_next_steps(
        severity=session.current_severity,
        alert_triggered=False,
        follow_up_recommended=True,
    )
    summary = CallSummary(
        call_id=session.call_id,
        procedure_id=session.procedure_id,
        procedure_scenario=session.procedure_scenario,
        postop_day=session.postop_day,
        patient_name=session.patient_name,
        patient_id=session.patient_id,
        final_score=session.cumulative_score,
        severity=session.current_severity,
        decision_label=session.current_severity.value,
        symptoms_reported=symptoms_reported,
        next_steps=next_steps,
        alert_triggered=False,
        sources_used=["guia_apendicitis.pdf"],
        turn_count=2,
        closed_reason="max_turns",
        turn_history=session.turns,
    )

    text = build_clinical_summary(
        session,
        summary,
        source_labels={"guia_apendicitis.pdf": "guia_apendicitis.pdf"},
    )

    assert "Ana López" in text
    assert "PAC-101" in text
    assert "AMARILLO" in text
    assert "guia_apendicitis.pdf" in text
    assert "src_" not in text
    assert "Vigilancia activa" in summary.next_steps
    assert (
        "fiebre"
        in format_symptoms_reported_text(
            symptoms_reported,
            labels={"fiebre": "¿Ha tenido fiebre?", "dolor": "¿Cómo califica su dolor?"},
        ).lower()
    )


def test_format_sources_used_text_prefers_document_names() -> None:
    text = format_sources_used_text(
        ["src_a", "src_b", "src_a"],
        source_labels={
            "src_a": "guia_postoperatoria.pdf",
            "src_b": "protocolo_dolor.pdf",
        },
    )
    assert text == "guia_postoperatoria.pdf, protocolo_dolor.pdf"


def test_replace_clinical_summary_sources_updates_tail() -> None:
    original = "Paciente Ana. Fuentes clínicas consultadas: src_a, src_b."
    updated = replace_clinical_summary_sources(original, "guia.pdf, otro.pdf")
    assert updated == "Paciente Ana. Fuentes clínicas consultadas: guia.pdf, otro.pdf."


def test_resolve_call_triage_escalates_on_consolidated_wound_infection() -> None:
    from knowledge.protocol.loader import load_protocol_for_procedure

    protocol, _ = load_protocol_for_procedure("total-joint-replacement")
    session = CallSessionState(
        call_id=uuid4(),
        procedure_id="total-joint-replacement",
        procedure_scenario=ProcedureScenario.TOTAL_JOINT_REPLACEMENT,
        postop_day=3,
        protocol_symptoms=[symptom.model_dump() for symptom in protocol.symptoms],
        protocol_thresholds=protocol.thresholds.model_dump(),
        turns=[
            TurnRecord(
                turn_number=1,
                patient_input="No tengo fiebre",
                agent_response="¿Cómo está la herida?",
                rag_query="fiebre",
                symptoms={"fiebre": False, "dolor_intenso": 5},
            ),
            TurnRecord(
                turn_number=2,
                patient_input="La herida supura",
                agent_response="Gracias.",
                rag_query="herida",
                symptoms={"infeccion_herida": "si"},
                alert_triggered=False,
            ),
        ],
        cumulative_score=10,
        current_severity=SeverityLevel.YELLOW,
        alert_triggered=False,
    )

    severity, alert, next_steps, follow_up = resolve_call_triage(
        session,
        closed_reason="max_turns_reached",
    )

    assert severity == SeverityLevel.RED
    assert alert is True
    assert follow_up is False
    assert "evaluación presencial" in next_steps.lower()
    assert "vigilancia" not in next_steps.lower()
