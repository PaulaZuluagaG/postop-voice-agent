"""Retry helpers for transient failures."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

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

_RETRY_AFTER_PATTERN = re.compile(
    r"try again in (\d+(?:\.\d+)?)\s*(s|ms|m)\b",
    re.IGNORECASE,
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
) -> float:
    parsed = groq_retry_delay_seconds(exc)
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
) -> T:
    """Execute *operation* with exponential backoff on transient errors."""
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except retryable_exceptions as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            delay = _retry_delay(
                exc,
                attempt,
                base_delay_seconds=base_delay_seconds,
                backoff_factor=backoff_factor,
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
    )
