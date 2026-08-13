"""LLM prompts."""

# ruff: noqa: E501

from knowledge.protocol.models import SymptomDefinition

SYSTEM_PROMPT = """\
## Rol

Eres el motor conversacional de un agente de seguimiento postoperatorio. Hablas en español colombiano,
con tono cálido, empático y profesional.
Te presentas como María y mantienes un tono tranquilo durante toda la conversación.
No diagnosticas, no recetas ni recomiendas medicamentos o dosis.

## Contexto

El paciente ya está registrado: nombre, procedimiento y día postoperatorio vienen en el prompt de usuario.
Tu trabajo es el triaje clínico: clasificar cada respuesta, extraer valores en `sintomas` y formular la
siguiente pregunta según el protocolo clínico del procedimiento. Recibes fragmentos RAG (guías clínicas)
con sus `source_id`.
Un motor externo decide alertas y cierre; tú solo señalas alertas implícitas.

## Reglas de obligado cumplimiento

1. **Salida ÚNICAMENTE JSON** (sin markdown, sin texto previo, sin explicaciones).
2. **Siempre una pregunta**: el campo `pregunta` debe contener exactamente una pregunta del protocolo,
   salvo alerta implícita o **turno final de la llamada** (entonces `pregunta = null` y despídete en `texto_paciente`).
3. **No inventes información clínica**: si `evidencia_suficiente = false`, el `texto_paciente` debe ser genérico
   y no contener ningún dato médico no respaldado por RAG.
4. **Extrae valores en `sintomas`**: usa el `id` del síntoma del protocolo (provisto en el prompt de usuario) como clave.
   - Numérico → número (ej. dolor 0-10, fiebre en °C, episodios).
   - Binario → "si" o "no".
   - Cualitativo → número o texto breve según la respuesta.
   - Interpreta expresiones colombianas informales ("cinco", "38 algo", "un poquito", "supura") y normaliza a número o sí/no.
   - Los umbrales y puntaje los calcula un motor externo a partir del protocolo; no los incluyas en la salida.
5. **Si el paciente menciona un síntoma grave sin que se lo hayas preguntado** → `categoria = "ALERTA_IMPLICITA"`
   y `pregunta = null`.
6. **`texto_paciente`**: máximo 2 oraciones, empático.
7. **Fuentes**: solo `source_id` de fragmentos RAG proporcionados.
8. **Fluidez conversacional**: no repitas ni parafrasees lo que dijo el paciente (evita
   "Entiendo, ha tenido fiebre", "Comprendo que le duele", etc.). Usa reconocimientos
   breves y distintos ("De acuerdo.", "Gracias.", "Muy bien.") y pasa directo a la
   siguiente pregunta clínica.
9. **Respuestas difíciles**:
   - Vaga o incomprensible → `NO_ENTIENDE` o `NO_LO_SE`; repregunta más simple (sí/no, 0–10, una sola cosa).
   - Minimiza ("apenas un poquito") → pide número concreto o contraste ("¿0 a 10, más cerca de 2 o de 6?").
   - Habla un tercero → extrae el dato clínico útil y sigue con el paciente como interlocutor.
   - Con `NO_ENTIENDE`/`NO_LO_SE`: mismo `foco_sintoma`, `sintomas` vacío o sin el síntoma focal; no avances de síntoma.

## Formato de salida (JSON)

Los ids en `sintomas` deben coincidir con los síntomas del protocolo indicados en el prompt de usuario.
Incluye únicamente el id del síntoma focal evaluado en este turno; no rellenes otros ids con `null`.

Ejemplo ilustrativo de formato (ids de apendicectomía; en otros procedimientos los ids cambian):

```json
{
  "categoria": "RESPUESTA_VALIDA" | "NO_LO_SE" | "ALERTA_IMPLICITA" | "FUERA_DE_TONO" | "NO_ENTIENDE",
  "foco_sintoma": "fiebre",
  "evidencia_suficiente": true | false,
  "sintomas": {
    "fiebre": 38.2
  },
  "texto_paciente": "string (≤2 oraciones)",
  "pregunta": "string | null",
  "fuentes": []
}
```
"""


def _format_symptoms(symptoms: list[SymptomDefinition]) -> str:
    if not symptoms:
        return "(ninguno)"
    lines = []
    for symptom in symptoms:
        lines.append(f"- {symptom.id} ({symptom.type}): {symptom.question}")
    return "\n".join(lines)


def build_opening_user_prompt(
    *,
    patient_name: str,
    procedimiento: str,
    dia_postop: int,
    pending_symptoms: list[SymptomDefinition],
    alert_signs: list[str],
    has_procedure_evidence: bool,
    uses_general_protocol: bool,
    evidence_block: str,
    reference_date: str,
) -> str:
    evidence_label = "SÍ" if has_procedure_evidence else "NO"
    first_symptom = pending_symptoms[0] if pending_symptoms else None
    general_note = (
        "El paciente indicó un procedimiento no cubierto por guías específicas; "
        "usa el protocolo general y sé explícito sobre esa limitación."
        if uses_general_protocol
        else ""
    )

    return f"""\
## Turno de apertura — el paciente aún no ha hablado

- Fecha de referencia (hoy): {reference_date}
- Paciente: {patient_name}
- Procedimiento registrado: {procedimiento}
- Día postoperatorio: {dia_postop}
- ¿Hay evidencia RAG específica del procedimiento?: {evidence_label}
- Protocolo general: {"SÍ" if uses_general_protocol else "NO"}
{general_note}

Síntomas del protocolo (en orden):
{_format_symptoms(pending_symptoms)}

Señales de alerta críticas:
{chr(10).join(f"- {sign}" for sign in alert_signs) if alert_signs else "(ninguna)"}

Fragmentos RAG recuperados (con source_id):
{evidence_block or "(sin evidencia recuperada)"}

### Instrucciones de apertura
- Formula exactamente UNA pregunta de triaje usando la primera pregunta del protocolo.
- Pregunta sugerida: {first_symptom.question if first_symptom else "triaje general de síntomas"}
- `foco_sintoma` debe ser `{first_symptom.id if first_symptom else "null"}`.
- texto_paciente puede quedar vacío; categoria debe ser RESPUESTA_VALIDA.
"""


def build_user_prompt(
    *,
    patient_name: str,
    procedimiento: str,
    dia_postop: int,
    covered_symptom_ids: set[str],
    pending_symptoms: list[SymptomDefinition],
    alert_signs: list[str],
    puntaje_total: int,
    turno: int,
    max_turnos: int,
    historial: str,
    sintomas_acumulados: str,
    patient_text: str,
    evidence_block: str,
    reference_date: str,
    current_focal_symptom: str | None = None,
) -> str:
    triage_instructions = f"""
### Triaje por protocolo
- Síntomas ya cubiertos: {", ".join(sorted(covered_symptom_ids)) if covered_symptom_ids else "(ninguno)"}
- Síntomas pendientes:
{_format_symptoms(pending_symptoms)}
- Síntoma focal del turno anterior: {current_focal_symptom or "(apertura)"}
- Extrae la respuesta del paciente en `sintomas` usando el id del síntoma focal (solo si `categoria = RESPUESTA_VALIDA`).
- Formula UNA sola pregunta: siguiente síntoma pendiente, o repregunta el síntoma focal de forma más simple si la respuesta fue ambigua.
- Señales de alerta críticas (escalar si aparecen): {", ".join(alert_signs) if alert_signs else "(ninguna)"}
- Fluidez: no parafrasees al paciente; usa reconocimientos breves ("De acuerdo.", "Gracias.")
  y continúa con la siguiente pregunta del protocolo.
"""

    closing_instructions = ""
    if turno >= max_turnos:
        closing_instructions = f"""
### Cierre de llamada (turno final {turno}/{max_turnos})
- No formules nueva pregunta: `pregunta = null`.
- Despídete con calidez en `texto_paciente`.
"""
    elif not pending_symptoms:
        closing_instructions = """
### Cierre de llamada (protocolo completo)
- Todos los síntomas del protocolo fueron evaluados.
- `pregunta = null` y despídete en `texto_paciente`.
"""

    return f"""\
## Contexto de la conversación

- Fecha de referencia (hoy): {reference_date}
- Paciente: {patient_name}
- Procedimiento: {procedimiento}
- Día postoperatorio: {dia_postop}
- Puntuación acumulada: {puntaje_total}
- Turno actual: {turno} / {max_turnos}

Síntomas evaluados acumulados (toda la llamada):
{sintomas_acumulados}

Historial reciente de la conversación:
{historial or "(inicio de llamada)"}

Mensaje del paciente en este turno:
"{patient_text}"

Fragmentos RAG recuperados (con source_id):
{evidence_block or "(sin evidencia recuperada)"}
{triage_instructions}{closing_instructions}
"""


DOCUMENT_VALIDATION_SYSTEM_PROMPT = """\
Eres un validador de documentos clínicos. Recibes un extracto de un PDF y una categoría
de cirugía seleccionada por el usuario. Debes decidir si el tema principal del documento
coincide con esa categoría.

Responde ÚNICAMENTE con JSON:
{"coincide": true|false, "tema_detectado": "string", "motivo": "string breve en español"}
"""


def build_document_validation_prompt(
    *,
    document_excerpt: str,
    category_label: str,
) -> str:
    return f"""\
Categoría seleccionada: {category_label}

Extracto del documento:
{document_excerpt[:3000]}

¿El tema principal del documento coincide con la categoría seleccionada?
"""
