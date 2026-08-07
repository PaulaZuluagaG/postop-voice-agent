"""Fixed escalation and disclaimer messages."""

ALERT_MESSAGE = (
    "Por sus síntomas, es importante que contacte de inmediato a su equipo de salud "
    "para una evaluación presencial. No es una emergencia que requiera llamar al 911, "
    "pero sí necesita atención médica hoy."
)

MAX_TURNS_CLOSE_MESSAGE = (
    "Hemos completado el seguimiento de esta llamada. Si presenta nuevos síntomas, "
    "contacte a su equipo de salud."
)


def build_no_evidence_message(topics: list[str]) -> str:
    if topics:
        joined = ", ".join(topics[:2])
        return (
            f"No tengo información sobre {joined} en mis guías disponibles. "
            "¿Puede describirme con más detalle sus síntomas principales?"
        )
    return (
        "No tengo información suficiente en mis guías para responder eso con certeza. "
        "¿Puede contarme qué síntoma le preocupa más en este momento?"
    )
