"""Normalize raw LLM JSON payloads before Pydantic validation."""

from __future__ import annotations

from typing import Any

from core.models import coerce_yes_no

_YES_NO_HECHOS_KEYS = frozenset({"DISNEA", "SANGREADO", "CONFUSION"})


def normalize_llm_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce common LLM format drift (e.g. booleans for yes/no fields)."""
    normalized = dict(payload)
    hechos = normalized.get("hechos")
    if not isinstance(hechos, dict):
        return normalized

    hechos_copy = dict(hechos)
    for key, value in hechos.items():
        canonical = key.upper() if isinstance(key, str) else key
        if canonical not in _YES_NO_HECHOS_KEYS:
            continue
        coerced = coerce_yes_no(value)
        if coerced is not None:
            hechos_copy[key] = coerced.value

    normalized["hechos"] = hechos_copy
    return normalized
