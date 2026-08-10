"""Prompt templates for clinical protocol extraction."""

# ruff: noqa: E501

PROTOCOL_SYSTEM_PROMPT_TEMPLATE = """\
Eres un experto en extracción clínica postoperatoria. Debes generar un protocolo de seguimiento postoperatorio en formato JSON válido.

[ESQUEMA OBLIGATORIO]
{{
  "procedure": "string",
  "symptoms": [{{
    "id": "string_snake_case",
    "question": "string",
    "type": "numeric" | "binary" | "qualitative",
    "levels": [{{"min": number, "max": number, "points": int, "label": "verde"|"amarillo"|"rojo"}}],
    "fuentes": ["source_id"]
  }}],
  "thresholds": {{"verde": int, "amarillo": int, "rojo": int}},
  "alert_signs": ["string"]
}}

[REQUISITOS OBLIGATORIOS]
- Si se mencionan múltiples síntomas, incluye todos los que sean relevantes SOLO para el seguimiento postoperatorio.
- Prioriza lo explícito en los fragmentos. No inventes síntomas sin respaldo textual.
- Si los fragmentos describen complicaciones, signos de alarma, advertencias o síntomas de riesgo (aunque no estén en formato de pregunta), conviértelos en preguntas de triage telefónico.
- Si hay al menos una complicación o signo de alarma descrito, incluye entre 3 y {max_symptoms} síntomas derivados de ese contenido.
- Máximo {max_symptoms} síntomas en "symptoms" (una pregunta por turno de llamada).
- Si faltan rangos: leve 0-3, moderado 4-7, grave 8-10; umbrales verde=0, amarillo=8, rojo=15.
- Binarios: min=0,max=0 para "no"; min=1,max=1 para "sí".
- Incluye source_ids reales en "fuentes" por síntoma.
- Extrae también "alert_signs" como lista de strings cuando el texto los mencione.

[EJEMPLO DE PROTOCOLO]
{{
  "procedure": "total_joint_replacement",
  "symptoms": [
    {{
      "id": "fiebre",
      "question": "¿Ha tenido fiebre? ¿Cuál es su temperatura?",
      "type": "numeric",
      "levels": [
        {{"min": 0, "max": 37.4, "points": 0, "label": "verde"}},
        {{"min": 37.5, "max": 38.4, "points": 4, "label": "amarillo"}},
        {{"min": 38.5, "max": 42, "points": 10, "label": "rojo"}}
      ],
      "fuentes": ["doc_apendicitis_01", "doc_apendicitis_02"]
    }},
    {{
      "id": "nauseas",
      "question": "¿Ha tenido náuseas o vómitos? ¿Cuántos episodios?",
      "type": "numeric",
      "levels": [
        {{"min": 0, "max": 0, "points": 0, "label": "verde"}},
        {{"min": 1, "max": 2, "points": 4, "label": "amarillo"}},
        {{"min": 3, "max": 100, "points": 10, "label": "rojo"}}
      ],
      "fuentes": ["doc_apendicitis_01", "doc_apendicitis_02"]
    }},
  ],
  "thresholds": {{"verde": 0, "amarillo": 8, "rojo": 15}},
  "alert_signs": []
}}

[EJEMPLO ONCOLOGÍA — complicaciones descritas en prosa]
Entrada: "Fiebre >38°C, sangrado abundante, dolor abdominal progresivo requieren valoración urgente."
Salida esperada: síntomas para fiebre, sangrado y dolor; alert_signs con esas complicaciones.
"""

PROTOCOL_USER_PROMPT_TEMPLATE = """\
Procedimiento: {procedure}

Fragmentos clínicos:
{text}

Extrae el protocolo postoperatorio en JSON. Entre 1 y {max_symptoms} síntomas. Sin markdown ni texto extra.
"""

PROTOCOL_COMPACT_USER_SUFFIX = """\
Modo compacto: máximo {max_symptoms} síntomas, preguntas breves (≤80 caracteres), \
solo 3 levels por síntoma numérico, JSON mínimo sin campos extra.
"""


def build_protocol_system_prompt(*, max_symptoms: int) -> str:
    return PROTOCOL_SYSTEM_PROMPT_TEMPLATE.format(max_symptoms=max_symptoms)


def build_protocol_user_prompt(
    *,
    procedure: str,
    text: str,
    max_symptoms: int,
    compact: bool = False,
    compact_max_symptoms: int | None = None,
) -> str:
    prompt = PROTOCOL_USER_PROMPT_TEMPLATE.format(
        procedure=procedure,
        text=text,
        max_symptoms=max_symptoms,
    )
    if compact:
        resolved_compact_max = (
            compact_max_symptoms if compact_max_symptoms is not None else max_symptoms
        )
        prompt += "\n" + PROTOCOL_COMPACT_USER_SUFFIX.format(max_symptoms=resolved_compact_max)
    return prompt


def truncate_fragment_text(text: str, max_chars: int) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 3].rstrip() + "..."


def format_protocol_fragments(
    fragments: list[tuple[int, str, str, str]],
    *,
    max_chars: int = 700,
) -> str:
    """Format RAG fragments for the extraction prompt."""
    seen_texts: set[str] = set()
    parts: list[str] = []
    for index, source_id, file_name, text in fragments:
        truncated = truncate_fragment_text(text, max_chars)
        dedupe_key = truncated[:200]
        if dedupe_key in seen_texts:
            continue
        seen_texts.add(dedupe_key)
        parts.append(f"--- Fragmento {index} (source_id: {source_id} | {file_name}) ---")
        parts.append(truncated)
        parts.append("")
    return "\n".join(parts).strip()
