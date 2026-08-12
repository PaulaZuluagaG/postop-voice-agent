"""Tests for Groq rate-limit error classification."""

from __future__ import annotations

import httpx
from groq import RateLimitError

from core.exceptions import LLMError, LLMRateLimitError
from core.llm_errors import groq_failure_to_llm_error


def _rate_limit_error(message: str) -> RateLimitError:
    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    return RateLimitError(message, response=response, body=None)


def test_groq_failure_to_llm_error_maps_rate_limit() -> None:
    exc = _rate_limit_error("tokens per day limit reached")
    mapped = groq_failure_to_llm_error(exc, prefix="Groq streaming failed")
    assert isinstance(mapped, LLMRateLimitError)
    assert "Groq streaming failed" in str(mapped)


def test_groq_failure_to_llm_error_preserves_wrapped_rate_limit() -> None:
    rate_exc = _rate_limit_error("429 rate_limit_exceeded")
    try:
        raise LLMError("Groq streaming failed: quota") from rate_exc
    except LLMError as wrapped:
        mapped = groq_failure_to_llm_error(wrapped, prefix="Groq streaming failed")
    assert isinstance(mapped, LLMRateLimitError)


def test_groq_failure_to_llm_error_keeps_generic_llm_error() -> None:
    exc = LLMError("Invalid JSON from Groq")
    mapped = groq_failure_to_llm_error(exc, prefix="Groq streaming failed")
    assert mapped is exc
