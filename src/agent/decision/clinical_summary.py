"""Deterministic clinical call summaries for care teams (no LLM)."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from core.config import Settings, get_settings
from core.models import CallSessionState, CallSummary, SeverityLevel
from core.scenarios import scenario_label

logger = logging.getLogger(__name__)
SOURCES_MARKER = "Fuentes clínicas consultadas: "


def consolidate_symptoms_reported(session: CallSessionState) -> dict[str, object]:
    """Merge symptom values reported across all turns (latest value wins)."""
    merged: dict[str, object] = {}
    for turn in session.turns:
        for symptom_id, value in turn.symptoms.items():
            if value is not None:
                merged[symptom_id] = value
    return merged


def _symptom_labels(session: CallSessionState) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in session.protocol_symptoms:
        if not isinstance(item, dict):
            continue
        symptom_id = str(item.get("id") or "").strip()
        if not symptom_id:
            continue
        question = str(item.get("question") or symptom_id).strip()
        labels[symptom_id] = question
    return labels


def _format_symptom_value(value: object) -> str:
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def format_symptoms_reported_text(
    symptoms: dict[str, object],
    *,
    labels: dict[str, str],
) -> str:
    if not symptoms:
        return "Sin síntomas cuantificados en la llamada."
    parts: list[str] = []
    for symptom_id in sorted(symptoms):
        label = labels.get(symptom_id, symptom_id.replace("_", " "))
        parts.append(f"{label}: {_format_symptom_value(symptoms[symptom_id])}")
    return "; ".join(parts)


def build_next_steps(
    *,
    severity: SeverityLevel,
    alert_triggered: bool,
    follow_up_recommended: bool,
) -> str:
    if alert_triggered or severity == SeverityLevel.RED:
        return "Escalar al equipo de salud hoy para evaluación presencial."
    if follow_up_recommended or severity == SeverityLevel.YELLOW:
        return (
            "Vigilancia activa: el equipo de salud debe contactar al paciente "
            "en las próximas 24 horas."
        )
    return (
        "Seguimiento rutinario completado. Contactar al equipo de salud "
        "si aparecen nuevos síntomas."
    )


def resolve_source_labels(
    source_ids: Iterable[str],
    *,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Map internal source_id values to indexed PDF file names."""
    ids = [source_id for source_id in source_ids if source_id]
    if not ids:
        return {}

    app_settings = settings or get_settings()
    try:
        from knowledge.store.qdrant_store import QdrantVectorStore

        by_id = {
            source.source_id: source.file_name
            for source in QdrantVectorStore(app_settings).list_sources()
            if source.source_id and source.file_name
        }
    except Exception:
        logger.warning("No se pudieron resolver nombres de fuentes clínicas", exc_info=True)
        by_id = {}

    return {source_id: by_id.get(source_id) or source_id for source_id in ids}


def format_sources_used_text(
    sources_used: list[str],
    *,
    source_labels: dict[str, str] | None = None,
) -> str:
    """Return deduplicated, human-readable document names for cited sources."""
    if not sources_used:
        return ""

    labels = source_labels or {}
    seen: set[str] = set()
    display: list[str] = []
    for source_id in sources_used:
        label = labels.get(source_id, source_id)
        if label not in seen:
            seen.add(label)
            display.append(label)
    return ", ".join(display)


def replace_clinical_summary_sources(clinical_summary: str, sources_text: str) -> str:
    """Swap the sources tail in a persisted summary paragraph."""
    if not clinical_summary or SOURCES_MARKER not in clinical_summary:
        return clinical_summary
    prefix, _ = clinical_summary.rsplit(SOURCES_MARKER, 1)
    return f"{prefix}{SOURCES_MARKER}{sources_text}."


def build_clinical_summary(
    session: CallSessionState,
    summary: CallSummary,
    *,
    source_labels: dict[str, str] | None = None,
) -> str:
    """Build a readable paragraph for the care team without calling an LLM."""
    procedure = summary.custom_procedure or scenario_label(summary.procedure_scenario)
    labels = _symptom_labels(session)
    symptoms_text = format_symptoms_reported_text(summary.symptoms_reported, labels=labels)
    decision = summary.decision_label.upper()

    lines = [
        (
            f"Paciente {summary.patient_name}"
            + (f" (ID {summary.patient_id})" if summary.patient_id else "")
            + f", seguimiento postoperatorio de {procedure}, día {summary.postop_day}."
        ),
        f"Síntomas reportados: {symptoms_text}",
        (
            f"Decisión de triaje: {decision} "
            f"(puntaje acumulado {summary.final_score}, "
            f"{'alerta clínica' if summary.alert_triggered else 'sin alerta automática'})."
        ),
        f"Próximo paso: {summary.next_steps}",
    ]
    if summary.sources_used:
        sources_text = format_sources_used_text(
            summary.sources_used,
            source_labels=source_labels,
        )
        lines.append(f"{SOURCES_MARKER}{sources_text}.")
    return " ".join(lines)
