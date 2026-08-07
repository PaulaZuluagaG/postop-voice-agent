from agent.decision.scoring import resolve_severity, score_turn, should_force_alert
from agent.messages import ALERT_MESSAGE, build_no_evidence_message
from core.models import PatientFacts, SeverityLevel


def test_fever_high_scores_ten_points() -> None:
    score, rules = score_turn(PatientFacts(fever_celsius=38.6))
    assert score == 10
    assert any("38.5" in rule for rule in rules)


def test_fever_moderate_scores_four_points() -> None:
    score, _ = score_turn(PatientFacts(fever_celsius=37.8))
    assert score == 4


def test_pain_and_dyspnea_accumulate() -> None:
    score, rules = score_turn(PatientFacts(pain=8.0, dyspnea=True))
    assert score == 20
    assert len(rules) == 2


def test_vomiting_threshold() -> None:
    score, rules = score_turn(PatientFacts(vomiting_count=3))
    assert score == 10
    assert any("Vómitos" in rule for rule in rules)


def test_cumulative_severity_thresholds() -> None:
    assert resolve_severity(7) == SeverityLevel.GREEN
    assert resolve_severity(8) == SeverityLevel.YELLOW
    assert resolve_severity(15) == SeverityLevel.RED


def test_implicit_alert_forces_escalation_with_low_score() -> None:
    assert should_force_alert(4, implicit_alert=True) is True
    assert should_force_alert(4, implicit_alert=False) is False
    assert should_force_alert(16, implicit_alert=False) is True


def test_alert_message_does_not_reference_911() -> None:
    assert "911" in ALERT_MESSAGE
    assert "equipo de salud" in ALERT_MESSAGE.lower()


def test_no_evidence_disclaimer_is_honest() -> None:
    message = build_no_evidence_message(["dosis de antibiótico"])
    assert "No tengo información" in message
    assert "dosis de antibiótico" in message
