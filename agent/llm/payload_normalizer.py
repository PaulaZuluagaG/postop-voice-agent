"""Normalize raw LLM JSON payloads before Pydantic validation."""

from __future__ import annotations

from typing import Any

from core.models import YesNo, coerce_episode_count, coerce_optional_float, coerce_yes_no

_YES_NO_HECHOS_KEYS = frozenset({"DISNEA", "SANGREADO", "CONFUSION", "VOMITOS"})
_NUMERIC_HECHOS_KEYS = frozenset({"DOLOR_0_10", "FIEBRE_C"})
_EPISODE_HECHOS_KEYS = frozenset({"VOMITOS_EPISODIOS"})


def _apply_vomiting_fact(hechos_copy: dict[str, Any], value: object) -> None:
    """Route legacy VOMITOS values to presence (si/no) or episode count."""
    episode_count = coerce_episode_count(value)
    if episode_count is not None and not isinstance(value, str):
        hechos_copy["VOMITOS_EPISODIOS"] = episode_count
        if episode_count > 0:
            hechos_copy["VOMITOS"] = YesNo.SI.value
        else:
            hechos_copy["VOMITOS"] = YesNo.NO.value
        return

    if isinstance(value, str) and value.strip().isdigit():
        count = int(value.strip())
        hechos_copy["VOMITOS_EPISODIOS"] = count
        hechos_copy["VOMITOS"] = YesNo.SI.value if count > 0 else YesNo.NO.value
        return

    coerced = coerce_yes_no(value)
    if coerced is not None:
        hechos_copy["VOMITOS"] = coerced.value


def normalize_llm_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce common LLM format drift (booleans, mixed vomiting facts, string numbers)."""
    normalized = dict(payload)
    hechos = normalized.get("hechos")
    if not isinstance(hechos, dict):
        return normalized

    hechos_copy = dict(hechos)
    for key, value in hechos.items():
        canonical = key.upper() if isinstance(key, str) else key
        if canonical in _NUMERIC_HECHOS_KEYS:
            coerced = coerce_optional_float(value)
            if coerced is not None:
                hechos_copy[key] = coerced
            continue
        if canonical == "VOMITOS":
            _apply_vomiting_fact(hechos_copy, value)
            continue
        if canonical in _EPISODE_HECHOS_KEYS:
            coerced = coerce_episode_count(value)
            if coerced is not None:
                hechos_copy[key] = coerced
            continue
        if canonical in _YES_NO_HECHOS_KEYS:
            coerced = coerce_yes_no(value)
            if coerced is not None:
                hechos_copy[key] = coerced.value

    normalized["hechos"] = hechos_copy
    return normalized
