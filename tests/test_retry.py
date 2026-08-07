"""Retry behavior tests."""

import pytest

from core.exceptions import PostOpError
from core.retry import with_retry


def test_with_retry_succeeds_on_third_attempt() -> None:
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("temporary")
        return "ok"

    result = with_retry(flaky, max_attempts=3, base_delay_seconds=0.01)
    assert result == "ok"
    assert attempts["count"] == 3


def test_with_retry_raises_after_max_attempts() -> None:
    def always_fail() -> None:
        raise TimeoutError("still failing")

    with pytest.raises(PostOpError):
        with_retry(always_fail, max_attempts=2, base_delay_seconds=0.01)
