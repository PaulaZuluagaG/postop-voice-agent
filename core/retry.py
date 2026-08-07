"""Retry helpers for transient failures."""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from core.exceptions import PostOpError

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


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
            delay = base_delay_seconds * (backoff_factor ** (attempt - 1))
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
