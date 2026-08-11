"""Protocol-driven triage symptom coverage."""

from __future__ import annotations

from core.models import LLMTurnOutput, ResponseCategory, YesNo, coerce_optional_float, coerce_yes_no
from knowledge.protocol.models import PostOpProtocol, SymptomDefinition


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


def _symptom_has_value(symptom_id: str, llm_output: LLMTurnOutput) -> bool:
    if symptom_id in llm_output.sintomas and llm_output.sintomas[symptom_id] is not None:
        return True
    return False


def extract_symptom_values(llm_output: LLMTurnOutput) -> dict[str, object]:
    values: dict[str, object] = {}
    for symptom_id, raw in llm_output.sintomas.items():
        if raw is None:
            continue
        values[symptom_id] = raw

    legacy_map = {
        "dolor": llm_output.hechos.dolor_0_10,
        "fiebre": llm_output.hechos.fiebre_c,
        "disnea": llm_output.hechos.disnea,
        "sangrado": llm_output.hechos.sangreado,
        "vomitos": llm_output.hechos.vomitos,
        "vomitos_episodios": llm_output.hechos.vomitos_episodios,
        "confusion": llm_output.hechos.confusion,
    }
    for symptom_id, raw in legacy_map.items():
        if raw is None or symptom_id in values:
            continue
        if isinstance(raw, YesNo):
            values[symptom_id] = raw.value
        else:
            values[symptom_id] = raw

    return values


def update_covered_symptoms(
    covered: set[str],
    llm_output: LLMTurnOutput,
    *,
    focal_symptom_id: str | None = None,
) -> set[str]:
    updated = set(covered)
    values = extract_symptom_values(llm_output)

    for symptom_id in values:
        updated.add(symptom_id)

    if focal_symptom_id and llm_output.categoria == ResponseCategory.RESPUESTA_VALIDA:
        if focal_symptom_id in values or _response_addresses_symptom(llm_output):
            updated.add(focal_symptom_id)

    if llm_output.foco_sintoma:
        updated.add(llm_output.foco_sintoma)

    return updated


def _response_addresses_symptom(llm_output: LLMTurnOutput) -> bool:
    return llm_output.categoria in {
        ResponseCategory.RESPUESTA_VALIDA,
        ResponseCategory.NO_LO_SE,
    } and bool(
        extract_symptom_values(llm_output) or llm_output.hechos.model_dump(exclude_none=True)
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
