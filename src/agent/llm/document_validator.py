"""Document category validation via Gemini (ingest batch pipeline)."""

from __future__ import annotations

from agent.llm.prompts import (
    DOCUMENT_VALIDATION_SYSTEM_PROMPT,
    build_document_validation_prompt,
)
from core.config import Settings, get_settings
from core.exceptions import LLMError
from core.gemini_client import GeminiClient
from core.models import ProcedureScenario
from core.scenarios import scenario_label


class DocumentValidator:
    """Validate uploaded PDFs against the selected surgery category."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._gemini = GeminiClient(self._settings)

    def validate_document_category(
        self,
        *,
        document_excerpt: str,
        procedure_scenario: ProcedureScenario,
    ) -> tuple[bool, str]:
        category_label = scenario_label(procedure_scenario)
        user_prompt = build_document_validation_prompt(
            document_excerpt=document_excerpt,
            category_label=category_label,
        )

        try:
            payload = self._gemini.generate_json(
                system_prompt=DOCUMENT_VALIDATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
                max_output_tokens=256,
                operation_name="gemini_validate_document",
            )
        except LLMError as exc:
            raise LLMError(f"Gemini document validation failed: {exc}") from exc

        coincide = bool(payload.get("coincide"))
        motivo = str(payload.get("motivo", "")).strip()
        if coincide:
            return True, motivo
        tema = str(payload.get("tema_detectado", "")).strip()
        detail = motivo or f"El documento parece tratar sobre {tema or 'otro tema'}."
        return False, (f"El documento no coincide con la categoría '{category_label}'. {detail}")
