"""Policy for when to replace LLM text with a no-evidence disclaimer.

The disclaimer exists to block ungrounded *medical information or advice*, not to
punish normal triage answers that do not need RAG citations.
"""

from __future__ import annotations

import re

from agent.decision.protocol_triage import has_structured_symptoms
from core.models import LLMTurnOutput, ResponseCategory

_REFORMULATION_CATEGORIES = frozenset(
    {
        ResponseCategory.NO_LO_SE,
        ResponseCategory.NO_ENTIENDE,
        ResponseCategory.FUERA_DE_TONO,
    }
)

# Patient is asking for clinical guidance, not answering triage.
_INFORMATION_SEEKING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\?"),
    re.compile(
        r"\b("
        r"que|qué|cu[aá]l|cu[aá]les|cu[aá]ndo|"
        r"c[oó]mo|d[oó]nde|por qu[eé]|"
        r"puedo|debo|deber[ií]a|"
        r"me recet|me mand|me dij|"
        r"es normal|est[aá] bien que|"
        r"cu[aá]nto tiempo|"
        r"antibi[oó]tic|medicament|pastill|analges|"
        r"dosis|tratamiento|diagn[oó]stic"
        r")\b",
        re.IGNORECASE,
    ),
)

# LLM is giving treatment or clinical advice without grounding.
_PRESCRIPTIVE_ADVICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b("
        r"debe tomar|debe usar|debe tomar|deber[ií]a tomar|"
        r"le recomiendo|recomiendo que|le sugiero|"
        r"tiene que tomar|necesita tomar|"
        r"prescri|administre|suspenda|"
        r"antibi[oó]tic|medicament|analges|"
        r"dosis|tratamiento|diagn[oó]stic"
        r")\b",
        re.IGNORECASE,
    ),
)


def patient_seeks_medical_information(patient_message: str) -> bool:
    """True when the patient asks for advice or clinical facts, not symptom reporting."""
    text = patient_message.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _INFORMATION_SEEKING_PATTERNS)


def llm_text_contains_prescriptive_advice(texto_paciente: str) -> bool:
    """True when agent text sounds like treatment or clinical guidance."""
    text = texto_paciente.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PRESCRIPTIVE_ADVICE_PATTERNS)


def is_grounded_in_rag(llm_output: LLMTurnOutput) -> bool:
    """True when the model claims sufficient evidence with citations."""
    return llm_output.evidencia_suficiente and bool(llm_output.fuentes)


def is_triage_symptom_exchange(llm_output: LLMTurnOutput, patient_message: str) -> bool:
    """Patient is answering triage questions rather than requesting medical facts."""
    if llm_output.categoria != ResponseCategory.RESPUESTA_VALIDA:
        return False
    if patient_seeks_medical_information(patient_message):
        return False
    if llm_output.foco_sintoma:
        return True
    if has_structured_symptoms(llm_output):
        return True
    # Short or declarative answers to agent questions (e.g. "4", "está sanando", "bien").
    return bool(patient_message.strip())


def should_replace_with_disclaimer(
    patient_message: str,
    llm_output: LLMTurnOutput,
) -> bool:
    """Decide whether to swap LLM empathy text for the fixed disclaimer."""
    if llm_output.categoria == ResponseCategory.ALERTA_IMPLICITA:
        return False

    if is_grounded_in_rag(llm_output):
        return False

    if llm_output.categoria in _REFORMULATION_CATEGORIES:
        return False

    if is_triage_symptom_exchange(llm_output, patient_message):
        return llm_text_contains_prescriptive_advice(llm_output.texto_paciente)

    if patient_seeks_medical_information(patient_message):
        return True

    return llm_text_contains_prescriptive_advice(llm_output.texto_paciente)
