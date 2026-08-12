"""Retry helpers for transient failures."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from groq import RateLimitError

from core.exceptions import PostOpError

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

GROQ_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    *DEFAULT_TRANSIENT_EXCEPTIONS,
    RateLimitError,
)

GEMINI_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    *DEFAULT_TRANSIENT_EXCEPTIONS,
    ResourceExhausted,
    ServiceUnavailable,
)

_RETRY_AFTER_PATTERN = re.compile(
    r"(?:try again in|retry in|please retry in)\s+(\d+(?:\.\d+)?)\s*(s|ms|m)\b",
    re.IGNORECASE,
)


def groq_is_daily_quota_error(exc: Exception) -> bool:
    """Return True when Groq hit the daily token quota (non-retryable)."""
    if not isinstance(exc, RateLimitError):
        return False
    parts = [exc.message.lower()]
    body = exc.body
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                parts.append(message.lower())
    combined = " ".join(parts)
    return "tokens per day" in combined or "tpd" in combined


def gemini_is_daily_quota_error(exc: Exception) -> bool:
    """Return True when Gemini hit the daily request quota (non-retryable)."""
    if not isinstance(exc, ResourceExhausted):
        return False
    normalized = str(exc).lower().replace("_", "").replace("-", "")
    return (
        "generatecontentpd" in normalized
        or "requestsperday" in normalized
        or "perdayperprojectpermodel" in normalized
    )


def groq_retry_delay_seconds(exc: Exception) -> float | None:
    """Parse Groq rate-limit hints from headers or error text."""
    if not isinstance(exc, RateLimitError):
        return None

    retry_after = exc.response.headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after) + 0.25
        except ValueError:
            pass

    match = _RETRY_AFTER_PATTERN.search(exc.message)
    if not match:
        return None

    return _parse_retry_delay_match(match)


def gemini_retry_delay_seconds(exc: Exception) -> float | None:
    """Parse Gemini 429 retry hints from error text or metadata."""
    if not isinstance(exc, ResourceExhausted):
        return None

    match = _RETRY_AFTER_PATTERN.search(str(exc))
    if match:
        return _parse_retry_delay_match(match)

    metadata = getattr(exc, "metadata", None)
    if metadata:
        retry_values = metadata.get("retry_delay", metadata.get("retry-delay"))
        if retry_values:
            try:
                return float(retry_values[0]) + 0.5
            except (TypeError, ValueError, IndexError):
                pass

    retry_delay = getattr(exc, "retry_delay", None)
    if retry_delay is not None:
        seconds = getattr(retry_delay, "seconds", None)
        if seconds is not None:
            return float(seconds) + 0.5

    return None


def _parse_retry_delay_match(match: re.Match[str]) -> float:
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "ms":
        return value / 1000 + 0.25
    if unit == "m":
        return value * 60 + 0.25
    return value + 0.25


def _retry_delay(
    exc: Exception,
    attempt: int,
    *,
    base_delay_seconds: float,
    backoff_factor: float,
    delay_parser: Callable[[Exception], float | None] | None = None,
) -> float:
    parser = delay_parser or groq_retry_delay_seconds
    parsed = parser(exc)
    if parsed is not None:
        return parsed
    return base_delay_seconds * (backoff_factor ** (attempt - 1))


def with_retry(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = DEFAULT_TRANSIENT_EXCEPTIONS,
    operation_name: str = "operation",
    is_non_retryable: Callable[[Exception], bool] | None = None,
    delay_parser: Callable[[Exception], float | None] | None = None,
) -> T:
    """Execute *operation* with exponential backoff on transient errors."""
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except retryable_exceptions as exc:
            last_error = exc
            if is_non_retryable and is_non_retryable(exc):
                break
            if attempt >= max_attempts:
                break
            delay = _retry_delay(
                exc,
                attempt,
                base_delay_seconds=base_delay_seconds,
                backoff_factor=backoff_factor,
                delay_parser=delay_parser,
            )
            logger.warning(
                "%s failed (attempt %s/%s): %s. Retrying in %.2fs",
                operation_name,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)

    assert last_error is not None
    if is_non_retryable and is_non_retryable(last_error):
        raise last_error
    if isinstance(last_error, PostOpError):
        raise last_error
    raise PostOpError(f"{operation_name} failed after {max_attempts} attempts") from last_error


def with_groq_retry(
    operation: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay_seconds: float = 0.5,
    backoff_factor: float = 2.0,
    operation_name: str = "groq_operation",
) -> T:
    """Retry Groq calls, honoring 429 retry-after hints when present."""
    return with_retry(
        operation,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        backoff_factor=backoff_factor,
        retryable_exceptions=GROQ_RETRYABLE_EXCEPTIONS,
        operation_name=operation_name,
        is_non_retryable=groq_is_daily_quota_error,
        delay_parser=groq_retry_delay_seconds,
    )


def with_gemini_retry(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 15.0,
    backoff_factor: float = 1.0,
    operation_name: str = "gemini_operation",
) -> T:
    """Retry Gemini calls, honoring RPM retry hints and failing fast on daily quota."""
    return with_retry(
        operation,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        backoff_factor=backoff_factor,
        retryable_exceptions=GEMINI_RETRYABLE_EXCEPTIONS,
        operation_name=operation_name,
        is_non_retryable=gemini_is_daily_quota_error,
        delay_parser=gemini_retry_delay_seconds,
    )
