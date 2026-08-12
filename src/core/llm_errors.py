"""Helpers for classifying LLM failures."""

from __future__ import annotations

from groq import RateLimitError

from core.exceptions import LLMError, LLMRateLimitError


def groq_failure_to_llm_error(exc: Exception, *, prefix: str) -> LLMError:
    """Map Groq client failures to typed LLM errors."""
    if isinstance(exc, LLMRateLimitError):
        return exc
    if isinstance(exc, LLMError):
        cause = exc.__cause__
        if isinstance(cause, RateLimitError):
            return LLMRateLimitError(f"{prefix}: {cause}")
        return exc
    if isinstance(exc, RateLimitError):
        return LLMRateLimitError(f"{prefix}: {exc}")
    return LLMError(f"{prefix}: {exc}")
