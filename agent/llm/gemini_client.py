"""Google Gemini 1.5 Flash client with structured JSON parsing."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import google.generativeai as genai
from google.generativeai.types import GenerationConfig

from agent.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from core.config import Settings, get_settings
from core.exceptions import ConfigurationError, LLMError
from core.models import LLMTurnOutput, RetrievedChunk
from core.retry import with_retry

logger = logging.getLogger(__name__)


class GeminiClient:
    """Thin wrapper around Gemini for structured turn outputs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.google_api_key:
            raise ConfigurationError("GOOGLE_API_KEY is required for GeminiClient")
        genai.configure(api_key=self._settings.google_api_key)
        self._model = genai.GenerativeModel(
            model_name=self._settings.gemini_model,
            system_instruction=SYSTEM_PROMPT,
        )

    def generate_turn(
        self,
        *,
        patient_message: str,
        procedure_scenario: str,
        postop_day: int,
        conversation_history: str,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LLMTurnOutput:
        evidence_block = self._format_evidence(retrieved_chunks)
        user_prompt = build_user_prompt(
            patient_message=patient_message,
            procedure_scenario=procedure_scenario,
            postop_day=postop_day,
            conversation_history=conversation_history,
            evidence_block=evidence_block,
        )

        def _call() -> LLMTurnOutput:
            response = self._model.generate_content(
                contents=user_prompt,
                generation_config=GenerationConfig(
                    temperature=self._settings.gemini_temperature,
                    max_output_tokens=self._settings.gemini_max_output_tokens,
                    response_mime_type="application/json",
                ),
            )
            raw_text = response.text or ""
            payload = self._parse_json(raw_text)
            output = LLMTurnOutput.model_validate(payload)
            return self._validate_sources(output, retrieved_chunks)

        try:
            return with_retry(_call, operation_name="gemini_generate_turn")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini turn generation failed: {exc}") from exc

    @staticmethod
    def _format_evidence(chunks: list[RetrievedChunk]) -> str:
        if not chunks:
            return ""
        lines: list[str] = []
        for chunk in chunks:
            lines.append(
                f"[{chunk.source_id} | {chunk.file_name} | p.{chunk.page_start}-{chunk.page_end}]\n"
                f"{chunk.text[:700]}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _parse_json(raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    @staticmethod
    def _validate_sources(
        output: LLMTurnOutput,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LLMTurnOutput:
        valid_ids = {chunk.source_id for chunk in retrieved_chunks}
        filtered = [source_id for source_id in output.cited_source_ids if source_id in valid_ids]
        return output.model_copy(update={"cited_source_ids": filtered})
