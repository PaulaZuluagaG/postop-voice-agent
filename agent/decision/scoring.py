"""Clinical scoring and escalation logic (Python-only thresholds)."""

from __future__ import annotations

from core.config import Settings, get_settings
from core.models import PatientFacts, SeverityLevel


def score_turn(symptoms: PatientFacts) -> tuple[int, list[str]]:
    """Compute turn score and human-readable rules applied."""
    score = 0
    rules: list[str] = []

    if symptoms.fever_celsius is not None:
        if symptoms.fever_celsius >= 38.5:
            score += 10
            rules.append(f"Fiebre {symptoms.fever_celsius}°C ≥ 38.5 (+10)")
        elif symptoms.fever_celsius >= 37.5:
            score += 4
            rules.append(f"Fiebre {symptoms.fever_celsius}°C entre 37.5-38.4 (+4)")

    if symptoms.pain is not None:
        if symptoms.pain >= 8:
            score += 10
            rules.append(f"Dolor {symptoms.pain}/10 ≥ 8 (+10)")
        elif symptoms.pain >= 5:
            score += 4
            rules.append(f"Dolor {symptoms.pain}/10 entre 5-7 (+4)")

    for flag_name, active in (
        ("Disnea", symptoms.dyspnea),
        ("Sangrado", symptoms.bleeding),
        ("Confusión", symptoms.confusion),
    ):
        if active:
            score += 10
            rules.append(f"{flag_name} presente (+10)")

    if symptoms.vomiting_count is not None and symptoms.vomiting_count >= 3:
        score += 10
        rules.append(f"Vómitos {symptoms.vomiting_count} ≥ 3 (+10)")

    return score, rules


def resolve_severity(cumulative_score: int, settings: Settings | None = None) -> SeverityLevel:
    settings = settings or get_settings()
    if cumulative_score >= settings.alert_score_threshold:
        return SeverityLevel.RED
    if cumulative_score >= settings.yellow_score_threshold:
        return SeverityLevel.YELLOW
    return SeverityLevel.GREEN


def should_force_alert(
    cumulative_score: int,
    *,
    implicit_alert: bool,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    if cumulative_score >= settings.alert_score_threshold:
        return True
    return implicit_alert and cumulative_score < settings.alert_score_threshold
