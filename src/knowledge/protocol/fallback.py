"""Fallback helpers when generated protocols are sparse or empty."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge.protocol.models import PostOpProtocol, SymptomDefinition

BUNDLED_GENERAL_PROTOCOL = "general_protocol.json"


def _bundled_general_protocol_path() -> Path:
    return Path(__file__).resolve().parent / BUNDLED_GENERAL_PROTOCOL


def load_bundled_general_protocol() -> PostOpProtocol:
    """Load the static general protocol bundled with the repository."""
    payload = json.loads(_bundled_general_protocol_path().read_text(encoding="utf-8"))
    return PostOpProtocol.model_validate(payload)


def merge_with_general_fallback(
    protocol: PostOpProtocol,
    procedure: str,
    *,
    min_symptoms: int = 3,
    max_symptoms: int = 8,
) -> PostOpProtocol:
    """Supplement sparse LLM output with symptoms and alert signs from the general protocol."""
    if len(protocol.symptoms) >= min_symptoms:
        return protocol

    general = load_bundled_general_protocol()
    existing_ids = {symptom.id for symptom in protocol.symptoms}
    merged_symptoms: list[SymptomDefinition] = list(protocol.symptoms)

    for symptom in general.symptoms:
        if len(merged_symptoms) >= max_symptoms:
            break
        if symptom.id in existing_ids:
            continue
        merged_symptoms.append(symptom.model_copy())
        existing_ids.add(symptom.id)

    merged_alerts = list(
        dict.fromkeys([*protocol.alert_signs, *general.alert_signs]),
    )

    return protocol.model_copy(
        update={
            "procedure": procedure,
            "symptoms": merged_symptoms,
            "alert_signs": merged_alerts,
        },
    )
