"""Gemini client for deterministic protocol JSON generation."""

from __future__ import annotations

import logging

from core.config import Settings, get_settings
from core.exceptions import LLMError
from core.gemini_client import GeminiClient
from core.models import RetrievedChunk
from knowledge.protocol.models import PostOpProtocol
from knowledge.protocol.prompts import (
    build_protocol_system_prompt,
    build_protocol_user_prompt,
    format_protocol_fragments,
)

logger = logging.getLogger(__name__)


class ProtocolGeminiClient:
    """Generate structured protocols via Gemini JSON mode."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._gemini = GeminiClient(self._settings)

    def generate_protocol_json(
        self,
        procedure: str,
        fragments: list[RetrievedChunk],
        *,
        fragment_max_chars: int | None = None,
        max_output_tokens: int | None = None,
        compact: bool = False,
    ) -> PostOpProtocol:
        if not fragments:
            raise ValueError(f"No RAG fragments available for procedure '{procedure}'")

        resolved_fragment_max_chars = (
            fragment_max_chars
            if fragment_max_chars is not None
            else (
                self._settings.protocol_compact_fragment_max_chars
                if compact
                else self._settings.protocol_fragment_max_chars
            )
        )
        resolved_max_output_tokens = (
            max_output_tokens
            if max_output_tokens is not None
            else self._settings.protocol_max_output_tokens
        )
        user_prompt = build_protocol_user_prompt(
            procedure=procedure,
            text=format_protocol_fragments(
                [
                    (index + 1, chunk.source_id, chunk.file_name, chunk.text)
                    for index, chunk in enumerate(fragments)
                ],
                max_chars=resolved_fragment_max_chars,
            ),
            max_symptoms=self._settings.protocol_max_symptoms,
            compact=compact,
            compact_max_symptoms=self._settings.protocol_compact_max_symptoms,
        )

        try:
            payload = self._gemini.generate_json(
                system_prompt=build_protocol_system_prompt(
                    max_symptoms=self._settings.protocol_max_symptoms,
                ),
                user_prompt=user_prompt,
                temperature=self._settings.gemini_temperature,
                max_output_tokens=resolved_max_output_tokens,
                operation_name="gemini_generate_protocol",
            )
        except LLMError as exc:
            raise LLMError(f"Gemini protocol generation failed: {exc}") from exc

        source_ids = sorted({chunk.source_id for chunk in fragments if chunk.source_id})
        protocol = PostOpProtocol.from_llm_output(payload, source_ids=source_ids)
        return self._validate_protocol_sources(protocol, fragments)

    @staticmethod
    def _validate_protocol_sources(
        protocol: PostOpProtocol,
        fragments: list[RetrievedChunk],
    ) -> PostOpProtocol:
        valid_ids = {chunk.source_id for chunk in fragments if chunk.source_id}

        updated_symptoms = []
        for symptom in protocol.symptoms:
            filtered = [source_id for source_id in symptom.fuentes if source_id in valid_ids]
            updated_symptoms.append(symptom.model_copy(update={"fuentes": filtered}))

        updated_risk_factors = []
        for risk_factor in protocol.risk_factors:
            filtered = [source_id for source_id in risk_factor.fuentes if source_id in valid_ids]
            if not filtered:
                continue
            updated_risk_factors.append(risk_factor.model_copy(update={"fuentes": filtered}))

        return protocol.model_copy(
            update={
                "symptoms": updated_symptoms,
                "risk_factors": updated_risk_factors,
            }
        )

    @staticmethod
    def _validate_symptom_sources(
        protocol: PostOpProtocol,
        fragments: list[RetrievedChunk],
    ) -> PostOpProtocol:
        """Backward-compatible alias for tests and callers."""
        return ProtocolGeminiClient._validate_protocol_sources(protocol, fragments)
