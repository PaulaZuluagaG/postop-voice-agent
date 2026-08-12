"""Intake helpers: procedure → scenario mapping and postop day calculation."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from core.models import ProcedureScenario

PROCEDURE_KEYWORDS: dict[ProcedureScenario, tuple[str, ...]] = {
    ProcedureScenario.APPENDICITIS: (
        "apendicectom",
        "apendicitis",
        "apendice",
    ),
    ProcedureScenario.CHOLECYSTITIS: (
        "colecistectom",
        "colelitiasis",
        "vesicula",
        "via biliar",
        "vias biliares",
    ),
    ProcedureScenario.COLORECTAL_CANCER: (
        "colorrectal",
        "colectom",
        "colon",
        "recto",
        "intestino grueso",
        "bowel surgery",
        "cancer de colon",
    ),
    ProcedureScenario.CERVICAL_CANCER: (
        "cuello uterino",
        "cervix",
        "cervical",
        "cancer de cuello uterino",
        "cancer cervical",
        "histerectom",
    ),
    ProcedureScenario.TOTAL_JOINT_REPLACEMENT: (
        "artroplast",
        "protesis de cadera",
        "protesis de rodilla",
        "reemplazo de cadera",
        "reemplazo de rodilla",
        "joint replacement",
        "cadera",
        "rodilla",
    ),
}

_DAYS_AGO = re.compile(r"^hace\s+(\d+)\s+dias?$")


def normalize_procedure_text(text: str) -> str:
    lowered = text.lower().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def map_procedure_to_scenario(procedure_text: str) -> ProcedureScenario:
    """Map free-text procedure name to the closest indexed scenario."""
    normalized = normalize_procedure_text(procedure_text)
    if not normalized:
        return ProcedureScenario.OTHER

    for scenario, keywords in PROCEDURE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return scenario
    return ProcedureScenario.OTHER


def detect_procedure_mismatch(
    patient_message: str,
    registered_scenario: ProcedureScenario,
) -> ProcedureScenario | None:
    """Return a different detected scenario when the patient mentions another surgery."""
    if registered_scenario == ProcedureScenario.OTHER:
        return None
    detected = map_procedure_to_scenario(patient_message)
    if detected == ProcedureScenario.OTHER or detected == registered_scenario:
        return None
    return detected


def parse_surgery_date(value: str) -> date:
    """Parse ISO 8601 date (YYYY-MM-DD or datetime prefix)."""
    cleaned = value.strip()
    if "T" in cleaned:
        cleaned = cleaned.split("T", maxsplit=1)[0]
    return date.fromisoformat(cleaned)


def try_resolve_relative_date(text: str, *, reference_date: date) -> date | None:
    """Resolve colloquial or ISO date strings; return None if not parseable."""
    normalized = normalize_procedure_text(text.strip())
    if not normalized:
        return None

    if normalized == "hoy":
        return reference_date
    if normalized == "ayer":
        return reference_date - timedelta(days=1)
    if normalized in {"antier", "anteayer"}:
        return reference_date - timedelta(days=2)

    days_ago = _DAYS_AGO.match(normalized)
    if days_ago:
        return reference_date - timedelta(days=int(days_ago.group(1)))

    if re.match(r"^\d{4}-\d{2}-\d{2}", normalized):
        try:
            return parse_surgery_date(text)
        except ValueError:
            return None
    return None


def resolve_surgery_date(value: str, *, reference_date: date | None = None) -> date:
    """Parse colloquial (ayer, hace N días) or ISO surgery dates."""
    ref = reference_date or date.today()
    resolved = try_resolve_relative_date(value, reference_date=ref)
    if resolved is not None:
        return resolved
    return parse_surgery_date(value)


def compute_postop_day(
    surgery_date: str | date,
    *,
    reference_date: date | None = None,
) -> int:
    """Return postoperative day; surgery day counts as day 1."""
    ref = reference_date or date.today()
    if isinstance(surgery_date, str):
        parsed = resolve_surgery_date(surgery_date, reference_date=ref)
    else:
        parsed = surgery_date
    return max(1, (ref - parsed).days + 1)


POSTOP_TIMEPOINTS: tuple[int, ...] = (1, 3, 7, 14)


def parse_postop_timepoint(value: object) -> int:
    """Validate a postoperative day from the intake UI (1, 3, 7 or 14)."""
    try:
        day = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("Día postoperatorio inválido.") from exc
    if day not in POSTOP_TIMEPOINTS:
        raise ValueError(f"Día postoperatorio inválido: {day}. Use 1, 3, 7 o 14.")
    return day
