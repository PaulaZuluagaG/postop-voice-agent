from agent.decision.protocol_triage import update_covered_symptoms
from agent.decision.scoring import (
    apply_cumulative_score,
    get_day_factor,
    resolve_severity,
    score_turn_from_protocol,
    should_force_alert,
)
from agent.messages import ALERT_MESSAGE, build_no_evidence_message
from core.models import (
    ClinicalFacts,
    LLMTurnOutput,
    ResponseCategory,
    SeverityLevel,
)
from knowledge.protocol.loader import load_general_protocol
from knowledge.protocol.models import ProtocolThresholds


def test_day_factor_schedule() -> None:
    assert get_day_factor(1) == 0.5
    assert get_day_factor(2) == 0.75
    assert get_day_factor(3) == 1.0
    assert get_day_factor(7) == 1.25
    assert get_day_factor(10) == 1.5


def test_protocol_fever_high_scores_with_day_factor() -> None:
    protocol = load_general_protocol()
    base, factor, weighted, rules = score_turn_from_protocol(
        {"fiebre": 38.6},
        protocol,
        postop_day=3,
    )
    assert base == 10
    assert factor == 1.0
    assert weighted == 10
    assert rules


def test_protocol_pain_and_dyspnea_accumulate() -> None:
    protocol = load_general_protocol()
    base, _factor, weighted, rules = score_turn_from_protocol(
        {"dolor": 8.0, "respiracion": "si"},
        protocol,
        postop_day=3,
    )
    assert base == 20
    assert weighted == 20
    assert len(rules) >= 2


def test_cumulative_severity_thresholds_from_protocol() -> None:
    thresholds = ProtocolThresholds(verde=0, amarillo=8, rojo=15)
    assert resolve_severity(7, thresholds) == SeverityLevel.GREEN
    assert resolve_severity(8, thresholds) == SeverityLevel.YELLOW
    assert resolve_severity(15, thresholds) == SeverityLevel.RED


def test_implicit_alert_forces_escalation_with_low_score() -> None:
    thresholds = ProtocolThresholds(verde=0, amarillo=8, rojo=15)
    assert should_force_alert(4, implicit_alert=True, critical_alert=False, thresholds=thresholds)
    assert not should_force_alert(
        4, implicit_alert=False, critical_alert=False, thresholds=thresholds
    )
    assert should_force_alert(16, implicit_alert=False, critical_alert=False, thresholds=thresholds)


def test_implicit_alert_forces_score_to_threshold() -> None:
    thresholds = ProtocolThresholds(verde=0, amarillo=8, rojo=15)
    cumulative, rules = apply_cumulative_score(
        4,
        0,
        categoria=ResponseCategory.ALERTA_IMPLICITA,
        thresholds=thresholds,
    )
    assert cumulative == 15
    assert any("Alerta implícita" in rule for rule in rules)


def test_update_covered_symptoms_from_sintomas_dict() -> None:
    output = LLMTurnOutput(
        categoria=ResponseCategory.RESPUESTA_VALIDA,
        foco_sintoma="dolor",
        sintomas={"dolor": 5.0},
        hechos=ClinicalFacts(),
        texto_paciente="Entendido.",
        pregunta="¿Ha tenido fiebre?",
    )
    covered = update_covered_symptoms(set(), output, focal_symptom_id="dolor")
    assert "dolor" in covered


def test_alert_message_does_not_reference_911() -> None:
    assert "911" in ALERT_MESSAGE
    assert "equipo de salud" in ALERT_MESSAGE.lower()


def test_no_evidence_disclaimer_is_honest() -> None:
    message = build_no_evidence_message(["dosis de antibiótico"])
    assert "No tengo información" in message
    assert "dosis de antibiótico" in message
