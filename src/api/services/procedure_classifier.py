"""LLM-based procedure suggestion for admin document uploads."""

from __future__ import annotations

from dataclasses import dataclass

from core.config import Settings, get_settings
from core.gemini_client import GeminiClient
from core.scenarios import (
    FOLDER_TO_SCENARIO,
    canonical_procedure_id,
    list_procedure_folders,
    normalize_procedure_id,
    procedure_display_label,
    scenario_label,
)


@dataclass(frozen=True)
class ProcedureSuggestionResult:
    procedure_id: str
    label_es: str


class ProcedureClassifier:
    """Suggest a procedure folder for an unknown clinical document."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._gemini = GeminiClient(self._settings)

    def suggest_procedure(
        self,
        *,
        document_excerpt: str,
        existing_procedures: list[str] | None = None,
    ) -> ProcedureSuggestionResult:
        procedures = existing_procedures or list_procedure_folders(self._settings.textos_dir)
        prompt = self._build_prompt(document_excerpt=document_excerpt, procedures=procedures)
        payload = self._gemini.generate_json(
            system_prompt=(
                "Eres un clasificador de documentos clínicos postoperatorios. "
                "Responde únicamente JSON con las claves suggested_procedure y procedure_label_es."
            ),
            user_prompt=prompt,
            operation_name="gemini_suggest_procedure",
        )
        suggested = str(payload.get("suggested_procedure", "")).strip()
        if not suggested:
            raise ValueError("El LLM no devolvió suggested_procedure")
        procedure_id = normalize_procedure_id(suggested)
        label_es = str(payload.get("procedure_label_es", "")).strip()
        return ProcedureSuggestionResult(
            procedure_id=procedure_id,
            label_es=self._resolve_label_es(procedure_id, label_es),
        )

    def _resolve_label_es(self, procedure_id: str, llm_label: str) -> str:
        canonical = canonical_procedure_id(procedure_id)
        scenario = FOLDER_TO_SCENARIO.get(canonical)
        if scenario is not None:
            return scenario_label(scenario)
        if llm_label:
            return llm_label
        return procedure_display_label(
            canonical,
            textos_dir=self._settings.textos_dir,
        )

    @staticmethod
    def _build_prompt(*, document_excerpt: str, procedures: list[str]) -> str:
        known = ", ".join(procedures) if procedures else "(ninguno)"
        return f"""\
Procedures existentes en el sistema (slugs en inglés para carpetas): {known}

Extracto del documento (inicio):
{document_excerpt[:3000]}

Analiza el extracto y responde JSON:
{{
  "suggested_procedure": "english-slug-for-folder",
  "procedure_label_es": "Nombre en español para la interfaz"
}}

Reglas:
- suggested_procedure: slug en inglés en kebab-case (ej. appendicitis, hernia-repair).
  Úsalo como nombre de carpeta bajo data/textos/.
- procedure_label_es: nombre clínico en español para mostrar al usuario
  (ej. "Apendicitis", "Reparación de hernia").
- Si el documento corresponde claramente a un procedure existente, devuelve ese slug
  y su etiqueta en español coherente con el procedimiento.
- Si representa un tipo nuevo, propone un slug nuevo en inglés y una etiqueta en español.
- Devuelve únicamente el JSON, sin texto adicional.
"""
