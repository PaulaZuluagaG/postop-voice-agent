"""Normalize raw LLM JSON payloads before Pydantic validation."""

from __future__ import annotations

from typing import Any

from core.models import coerce_episode_count, coerce_optional_float, coerce_yes_no


def _normalize_symptom_value(value: object) -> object:
    if isinstance(value, bool):
        yn = coerce_yes_no(value)
        return yn.value if yn is not None else value
    coerced_float = coerce_optional_float(value)
    if coerced_float is not None and not isinstance(value, str):
        return coerced_float
    coerced_count = coerce_episode_count(value)
    if coerced_count is not None and not isinstance(value, str):
        return coerced_count
    yn = coerce_yes_no(value)
    if yn is not None:
        return yn.value
    if isinstance(value, str):
        stripped = value.strip()
        coerced_float = coerce_optional_float(stripped)
        if coerced_float is not None:
            return coerced_float
        coerced_count = coerce_episode_count(stripped)
        if coerced_count is not None:
            return coerced_count
    return value


def normalize_llm_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce common LLM format drift in protocol symptom values."""
    normalized = dict(payload)
    sintomas = normalized.get("sintomas")
    if not isinstance(sintomas, dict):
        return normalized

    sintomas_copy: dict[str, object] = {}
    for key, value in sintomas.items():
        if value is None:
            sintomas_copy[key] = None
        else:
            sintomas_copy[key] = _normalize_symptom_value(value)

    normalized["sintomas"] = sintomas_copy
    normalized.pop("hechos", None)
    normalized.pop("foco", None)
    return normalized
