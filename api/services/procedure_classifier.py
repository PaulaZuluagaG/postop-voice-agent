"""LLM-based procedure suggestion for admin document uploads."""

from __future__ import annotations

from core.config import Settings, get_settings
from core.gemini_client import GeminiClient
from core.scenarios import list_procedure_folders, normalize_procedure_id


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
    ) -> str:
        procedures = existing_procedures or list_procedure_folders(self._settings.textos_dir)
        prompt = self._build_prompt(document_excerpt=document_excerpt, procedures=procedures)
        payload = self._gemini.generate_json(
            system_prompt=(
                "Eres un clasificador de documentos clínicos postoperatorios. "
                "Responde únicamente JSON con la clave suggested_procedure."
            ),
            user_prompt=prompt,
            operation_name="gemini_suggest_procedure",
        )
        suggested = str(payload.get("suggested_procedure", "")).strip()
        if not suggested:
            raise ValueError("El LLM no devolvió suggested_procedure")
        return normalize_procedure_id(suggested)

    @staticmethod
    def _build_prompt(*, document_excerpt: str, procedures: list[str]) -> str:
        known = ", ".join(procedures) if procedures else "(ninguno)"
        return f"""\
Procedures existentes en el sistema: {known}

Extracto del documento (inicio):
{document_excerpt[:3000]}

Analiza el extracto y responde JSON:
{{"suggested_procedure": "slug_en_minusculas"}}

Reglas:
- Si el documento corresponde claramente a uno de los procedures existentes, devuelve ese slug.
- Si representa un nuevo tipo de procedimiento, propone un slug nuevo en snake_case o kebab-case.
- Devuelve únicamente el slug, sin texto adicional.
"""
