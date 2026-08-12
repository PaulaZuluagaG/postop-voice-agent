"""Fixed escalation and disclaimer messages."""

from core.models import ProcedureScenario, SeverityLevel

ALERT_MESSAGE = (
    "Por sus síntomas, contacte hoy a su equipo de salud " "para una evaluación presencial."
)

GREEN_CLOSE_MESSAGE = (
    "Gracias por su tiempo. Hemos completado el seguimiento de hoy. "
    "Cuídese mucho y, si presenta nuevos síntomas, contacte a su equipo de salud."
)

YELLOW_CLOSE_MESSAGE = (
    "Sus síntomas requieren vigilancia; su equipo de salud debe contactarle "
    "en las próximas 24 horas. Gracias por su tiempo."
)

# Backward-compatible alias used in tests and legacy callers.
MAX_TURNS_CLOSE_MESSAGE = GREEN_CLOSE_MESSAGE

LLM_RATE_LIMIT_CLOSE_MESSAGE = (
    "Disculpe, en este momento no puedo continuar con el seguimiento por una limitación "
    "temporal del servicio. Por favor intente de nuevo más tarde. Gracias por su tiempo."
)


def closure_message_for_severity(severity: SeverityLevel) -> str:
    """Return the patient-facing closure line for the final triage severity."""
    if severity == SeverityLevel.RED:
        return ALERT_MESSAGE
    if severity == SeverityLevel.YELLOW:
        return YELLOW_CLOSE_MESSAGE
    return GREEN_CLOSE_MESSAGE


def build_procedure_evidence_notice(*, has_evidence: bool, procedure_name: str) -> str:
    """Return a patient-facing disclaimer only when procedure-specific docs are missing."""
    if has_evidence:
        return ""
    proc = procedure_name.strip() or "su procedimiento"
    return (
        f"No tengo guías clínicas ni documentos específicos sobre {proc} "
        "de donde extraer información; haré un triaje general de sus síntomas."
    )


def patient_first_name(full_name: str) -> str:
    """Return the first given name from the intake ``nombre`` field."""
    parts = full_name.strip().split()
    return parts[0] if parts else "Paciente"


def build_postop_day_context(postop_day: int) -> str:
    """Short recovery-stage line for the opening greeting."""
    if postop_day == 1:
        return "Es su primer día después de la cirugía"
    if postop_day == 3:
        return "Estamos en los primeros días de su recuperación"
    if postop_day == 7:
        return "Ya lleva una semana de recuperación"
    if postop_day >= 14:
        return "Ya van dos semanas de su recuperación"
    return f"Estamos en el día {postop_day} de su recuperación"


def build_opening_intro(
    *,
    patient_name: str,
    has_evidence: bool,
    procedure_name: str,
    postop_day: int,
) -> str:
    name = patient_first_name(patient_name)
    stage = build_postop_day_context(postop_day)
    parts = [
        f"Hola {name}, soy María, su asistente de seguimiento postoperatorio.",
        f"{stage}.",
        "Voy a hacerle unas preguntas para revisar cómo va su recuperación.",
    ]
    evidence = build_procedure_evidence_notice(
        has_evidence=has_evidence,
        procedure_name=procedure_name,
    )
    if evidence:
        parts.append(evidence)
    return " ".join(parts)


DEFAULT_OPENING_QUESTION = "Del 0 al 10, ¿qué tan fuerte es su dolor en este momento?"


def build_procedure_mismatch_message(
    mentioned_scenario: ProcedureScenario,
    registered_scenario: ProcedureScenario,
) -> str:
    from core.scenarios import scenario_label

    mentioned = scenario_label(mentioned_scenario)
    registered = scenario_label(registered_scenario)
    return (
        f"Entiendo su consulta sobre {mentioned}, pero no tengo documentación sobre ese "
        f"procedimiento en mis guías. Continuaré con el seguimiento de {registered}."
    )


def build_no_evidence_message(
    topics: list[str],
    *,
    include_redirect_question: bool = True,
) -> str:
    if topics:
        joined = ", ".join(topics[:2])
        statement = f"No tengo información sobre {joined} en mis guías disponibles."
    else:
        statement = "No tengo información suficiente en mis guías para responder eso con certeza."
    if not include_redirect_question:
        return statement
    if topics:
        return f"{statement} ¿Puede describirme con más detalle sus síntomas principales?"
    return f"{statement} ¿Puede contarme qué síntoma le preocupa más en este momento?"
