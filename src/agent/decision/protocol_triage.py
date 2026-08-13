"""Protocol-driven triage symptom coverage."""

from __future__ import annotations

from core.models import LLMTurnOutput, ResponseCategory, coerce_optional_float, coerce_yes_no
from knowledge.protocol.models import PostOpProtocol, SymptomDefinition

_AMBIGUOUS_CATEGORIES = frozenset(
    {
        ResponseCategory.NO_ENTIENDE,
        ResponseCategory.NO_LO_SE,
    }
)


def is_ambiguous_response(llm_output: LLMTurnOutput) -> bool:
    """True when the patient answer was vague or not understood."""
    return llm_output.categoria in _AMBIGUOUS_CATEGORIES


def pending_symptoms(
    protocol: PostOpProtocol,
    covered: set[str],
) -> list[SymptomDefinition]:
    return [symptom for symptom in protocol.symptoms if symptom.id not in covered]


def next_symptom(
    protocol: PostOpProtocol,
    covered: set[str],
) -> SymptomDefinition | None:
    pending = pending_symptoms(protocol, covered)
    return pending[0] if pending else None


def all_symptoms_covered(protocol: PostOpProtocol, covered: set[str]) -> bool:
    return len(pending_symptoms(protocol, covered)) == 0


def extract_symptom_values(llm_output: LLMTurnOutput) -> dict[str, object]:
    values: dict[str, object] = {}
    for symptom_id, raw in llm_output.sintomas.items():
        if raw is None:
            continue
        values[symptom_id] = raw
    return values


def has_structured_symptoms(llm_output: LLMTurnOutput) -> bool:
    return bool(extract_symptom_values(llm_output))


def update_covered_symptoms(
    covered: set[str],
    llm_output: LLMTurnOutput,
    *,
    focal_symptom_id: str | None = None,
) -> set[str]:
    updated = set(covered)
    if is_ambiguous_response(llm_output):
        return updated

    if llm_output.categoria != ResponseCategory.RESPUESTA_VALIDA:
        return updated

    values = extract_symptom_values(llm_output)

    for symptom_id in values:
        updated.add(symptom_id)

    if focal_symptom_id and (focal_symptom_id in values or _response_addresses_symptom(llm_output)):
        updated.add(focal_symptom_id)

    if llm_output.foco_sintoma and llm_output.foco_sintoma in values:
        updated.add(llm_output.foco_sintoma)

    return updated


def _response_addresses_symptom(llm_output: LLMTurnOutput) -> bool:
    return llm_output.categoria == ResponseCategory.RESPUESTA_VALIDA and has_structured_symptoms(
        llm_output
    )


def format_pending_symptoms(symptoms: list[SymptomDefinition]) -> str:
    if not symptoms:
        return "(ninguno)"
    lines = []
    for symptom in symptoms:
        lines.append(f"- {symptom.id} ({symptom.type}): {symptom.question}")
    return "\n".join(lines)


def format_alert_signs(signs: list[str]) -> str:
    if not signs:
        return "(ninguna)"
    return "\n".join(f"- {sign}" for sign in signs)


def coerce_symptom_response(value: object, symptom_type: str) -> object | None:
    if value is None:
        return None
    if symptom_type == "numeric":
        return coerce_optional_float(value)
    if symptom_type == "binary":
        yn = coerce_yes_no(value)
        if yn is not None:
            return yn.value
        numeric = coerce_optional_float(value)
        if numeric is not None:
            return numeric
    if symptom_type == "qualitative":
        numeric = coerce_optional_float(value)
        if numeric is not None:
            return numeric
        yn = coerce_yes_no(value)
        if yn is not None:
            return yn.value
        if isinstance(value, str) and value.strip():
            return value.strip()
    return value
