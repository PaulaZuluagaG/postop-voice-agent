"""Post-process agent wording for natural voice conversation."""

from __future__ import annotations

import re

from agent.decision.intake import normalize_procedure_text

_BRIEF_ACKS: tuple[str, ...] = (
    "De acuerdo.",
    "Entiendo.",
    "Gracias.",
    "Muy bien.",
    "Comprendo.",
)

_ECHO_LEADERS = re.compile(
    r"^(entiendo|comprendo|gracias por contarme|gracias por informarme|veo que|"
    r"noto que|me comenta que|me dice que|le entiendo)\b",
    re.IGNORECASE,
)


def _content_tokens(text: str) -> set[str]:
    normalized = normalize_procedure_text(text)
    return {token for token in normalized.split() if len(token) > 2}


def patient_echo_overlap(patient_message: str, agent_text: str) -> float:
    """Estimate how much of the patient message is paraphrased in the agent reply."""
    patient_tokens = _content_tokens(patient_message)
    if not patient_tokens:
        return 0.0
    agent_normalized = normalize_procedure_text(agent_text)
    matched = sum(1 for token in patient_tokens if token in agent_normalized)
    return matched / len(patient_tokens)


def soften_patient_echo(
    patient_message: str,
    agent_text: str,
    *,
    turn_index: int = 0,
) -> str:
    """Replace repetitive paraphrase with a short acknowledgment."""
    text = agent_text.strip()
    if not text or not patient_message.strip():
        return agent_text

    overlap = patient_echo_overlap(patient_message, text)
    if _ECHO_LEADERS.match(text) and overlap >= 0.25:
        return _BRIEF_ACKS[turn_index % len(_BRIEF_ACKS)]
    if overlap >= 0.55 and len(text.split()) <= 8:
        return _BRIEF_ACKS[turn_index % len(_BRIEF_ACKS)]
    return agent_text
