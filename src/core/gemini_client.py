"""Shared Gemini client for JSON-mode batch LLM tasks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import google.generativeai as genai

from core.config import Settings, get_settings
from core.exceptions import LLMError
from core.gemini_limiter import gemini_call_slot
from core.retry import with_gemini_retry

logger = logging.getLogger(__name__)


class GeminiClient:
    """Thin wrapper around Gemini for structured JSON outputs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is required for Gemini LLM operations")
        genai.configure(api_key=self._settings.gemini_api_key)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        operation_name: str = "gemini_generate_json",
    ) -> dict[str, Any]:
        resolved_temperature = (
            self._settings.gemini_temperature if temperature is None else temperature
        )
        resolved_max_tokens = (
            self._settings.gemini_max_output_tokens
            if max_output_tokens is None
            else max_output_tokens
        )
        max_json_attempts = self._settings.gemini_json_max_attempts

        def _call() -> dict[str, Any]:
            with gemini_call_slot():
                model = genai.GenerativeModel(
                    model_name=self._settings.gemini_model,
                    system_instruction=system_prompt,
                )
                response = model.generate_content(
                    user_prompt,
                    generation_config={
                        "temperature": resolved_temperature,
                        "max_output_tokens": resolved_max_tokens,
                        "response_mime_type": "application/json",
                    },
                )
            raw_text = self._extract_text(response)
            if not raw_text.strip():
                raise LLMError("Gemini returned an empty response")
            self._check_finish_reason(response)
            return self._parse_json(raw_text)

        last_json_error: LLMError | None = None
        for attempt in range(1, max_json_attempts + 1):
            try:
                return with_gemini_retry(_call, operation_name=operation_name)
            except LLMError as exc:
                last_json_error = exc
                message = str(exc).lower()
                retryable_json = (
                    "invalid json" in message
                    or "empty response" in message
                    or "truncated" in message
                )
                if not retryable_json or attempt >= max_json_attempts:
                    raise
                logger.warning(
                    "%s JSON parse failed (attempt %s/%s): %s",
                    operation_name,
                    attempt,
                    max_json_attempts,
                    exc,
                )

        assert last_json_error is not None
        raise last_json_error

    @staticmethod
    def _check_finish_reason(response: Any) -> None:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return
        finish_reason = getattr(candidates[0], "finish_reason", None)
        if finish_reason is None:
            return
        reason_name = getattr(finish_reason, "name", str(finish_reason)).upper()
        if reason_name in {"MAX_TOKENS", "2"}:
            raise LLMError("Gemini returned invalid JSON: output truncated (MAX_TOKENS)")

    @staticmethod
    def _extract_text(response: Any) -> str:
        parts_text: list[str] = []
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", None) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts_text.append(part_text)
        if parts_text:
            return "".join(parts_text)

        text = getattr(response, "text", None)
        return text or ""

    @staticmethod
    def _parse_json(raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                logger.error("Invalid JSON from Gemini: %s", cleaned[:500])
                raise LLMError("Gemini returned invalid JSON") from exc
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError as nested_exc:
                logger.error("Invalid JSON from Gemini: %s", cleaned[:500])
                raise LLMError("Gemini returned invalid JSON") from nested_exc
        if not isinstance(payload, dict):
            raise LLMError("Gemini JSON response must be an object")
        return payload
