"""Clinical scoring and escalation logic driven by protocol JSON."""

from __future__ import annotations

from core.models import ResponseCategory, SeverityLevel, YesNo, coerce_optional_float, coerce_yes_no
from knowledge.protocol.models import (
    PostOpProtocol,
    ProtocolThresholds,
    RiskFactorDefinition,
    SymptomDefinition,
    SymptomLevel,
)


def get_day_factor(dia_postop: int) -> float:
    """Scale symptom scores by recovery stage (Excel timepoints: 1, 3, 7, 14)."""
    if dia_postop == 1:
        return 0.5
    if dia_postop == 3:
        return 1.0
    if dia_postop == 7:
        return 1.25
    if dia_postop >= 14:
        return 1.5
    # Legacy / CLI dates between canonical timepoints
    if dia_postop == 2:
        return 0.75
    if 4 <= dia_postop <= 6:
        return 1.0
    if 8 <= dia_postop <= 13:
        return 1.375
    return 1.0


def _normalize_symptom_value(value: object) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        yn = coerce_yes_no(value)
        if yn == YesNo.SI:
            return 1.0
        if yn == YesNo.NO:
            return 0.0
    return coerce_optional_float(value)


def _match_level(value: float, levels: list[SymptomLevel]) -> SymptomLevel | None:
    for level in levels:
        if level.min <= value <= level.max:
            return level
    return None


def score_symptom(value: object, symptom: SymptomDefinition) -> tuple[int, list[str]]:
    numeric = _normalize_symptom_value(value)
    if numeric is None:
        return 0, []

    level = _match_level(numeric, symptom.levels)
    if level is None:
        return 0, []

    rules: list[str] = []
    if level.points:
        rules.append(f"{symptom.id}={numeric} → {level.label} (+{level.points})")
    return level.points, rules


def score_turn_from_protocol(
    symptom_values: dict[str, object],
    protocol: PostOpProtocol,
    postop_day: int,
) -> tuple[int, float, int, list[str]]:
    """Return ``(base_score, day_factor, weighted_score, rules)``."""
    base_score = 0
    rules: list[str] = []
    symptoms_by_id = {symptom.id: symptom for symptom in protocol.symptoms}

    for symptom_id, value in symptom_values.items():
        symptom = symptoms_by_id.get(symptom_id)
        if symptom is None or value is None:
            continue
        points, symptom_rules = score_symptom(value, symptom)
        base_score += points
        rules.extend(symptom_rules)

    day_factor = get_day_factor(postop_day)
    weighted_score = round(base_score * day_factor)
    if day_factor != 1.0 and base_score:
        rules.append(f"Factor día postop {postop_day}: ×{day_factor} → {weighted_score}")

    return base_score, day_factor, weighted_score, rules


def resolve_severity(cumulative_score: int, thresholds: ProtocolThresholds) -> SeverityLevel:
    if cumulative_score >= thresholds.rojo:
        return SeverityLevel.RED
    if cumulative_score >= thresholds.amarillo:
        return SeverityLevel.YELLOW
    return SeverityLevel.GREEN


def apply_cumulative_score(
    current_total: int,
    weighted_score: int,
    *,
    categoria: ResponseCategory,
    thresholds: ProtocolThresholds,
) -> tuple[int, list[str]]:
    rules: list[str] = []
    cumulative = current_total + weighted_score

    if categoria == ResponseCategory.ALERTA_IMPLICITA and cumulative < thresholds.rojo:
        cumulative = thresholds.rojo
        rules.append(f"Alerta implícita: puntaje forzado a {thresholds.rojo}")

    return cumulative, rules


def should_force_alert(
    cumulative_score: int,
    *,
    implicit_alert: bool,
    critical_alert: bool,
    thresholds: ProtocolThresholds,
) -> bool:
    if critical_alert:
        return True
    if cumulative_score >= thresholds.rojo:
        return True
    return implicit_alert and cumulative_score < thresholds.rojo


def _symptom_triggers_red(value: object, symptom: SymptomDefinition) -> bool:
    numeric = _normalize_symptom_value(value)
    if numeric is None:
        return False
    level = _match_level(numeric, symptom.levels)
    return level is not None and level.label == "rojo" and level.points >= 10


def detect_critical_alert(
    symptom_values: dict[str, object],
    protocol: PostOpProtocol,
    *,
    implicit_alert: bool = False,
) -> bool:
    if implicit_alert:
        return True

    symptoms_by_id = {symptom.id: symptom for symptom in protocol.symptoms}
    for symptom_id, value in symptom_values.items():
        symptom = symptoms_by_id.get(symptom_id)
        if symptom is None:
            continue
        if _symptom_triggers_red(value, symptom):
            return True

    return False


def apply_risk_factor_bonus(
    patient_comorbidities: list[str],
    protocol_risk_factors: list[RiskFactorDefinition],
    *,
    bonus_per_match: int,
) -> tuple[int, list[str]]:
    """Add a fixed bonus per matching comorbidity (patient ∩ protocol risk factors)."""
    if not patient_comorbidities or not protocol_risk_factors:
        return 0, []

    protocol_ids = {factor.id for factor in protocol_risk_factors}
    labels_by_id = {factor.id: factor.label for factor in protocol_risk_factors}
    matches = [comorbidity for comorbidity in patient_comorbidities if comorbidity in protocol_ids]
    if not matches:
        return 0, []

    bonus = len(matches) * bonus_per_match
    rules = [
        f"Factor de riesgo {labels_by_id[match]} ({match}): +{bonus_per_match}" for match in matches
    ]
    return bonus, rules
