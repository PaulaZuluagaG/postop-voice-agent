"""Fixed escalation and disclaimer messages."""

from core.models import ProcedureScenario

ALERT_MESSAGE = (
    "Por sus síntomas, es importante que contacte de inmediato a su equipo de salud "
    "para una evaluación presencial. No es una emergencia que requiera llamar al 911, "
    "pero sí necesita atención médica hoy."
)

MAX_TURNS_CLOSE_MESSAGE = (
    "Gracias por su tiempo. Hemos completado el seguimiento de hoy. "
    "Cuídese mucho y, si presenta nuevos síntomas, contacte a su equipo de salud."
)


def build_procedure_evidence_notice(*, has_evidence: bool, procedure_name: str) -> str:
    proc = procedure_name.strip() or "su procedimiento"
    if has_evidence:
        return f"Sí cuento con guías clínicas sobre {proc}."
    return (
        f"No tengo información específica sobre {proc} en mis guías disponibles. "
        "Haré un triaje general de sus síntomas."
    )


def build_opening_intro(
    *,
    patient_name: str,
    has_evidence: bool,
    procedure_name: str,
) -> str:
    name = patient_name.strip() or "Paciente"
    evidence = build_procedure_evidence_notice(
        has_evidence=has_evidence,
        procedure_name=procedure_name,
    )
    return f"Hola {name}, soy su asistente de seguimiento postoperatorio. " f"{evidence}"


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
