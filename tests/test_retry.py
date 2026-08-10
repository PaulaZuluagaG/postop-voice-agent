"""Retry behavior tests."""

import httpx
import pytest
from google.api_core.exceptions import ResourceExhausted
from groq import RateLimitError

from core.exceptions import PostOpError
from core.retry import (
    gemini_is_daily_quota_error,
    gemini_retry_delay_seconds,
    groq_retry_delay_seconds,
    with_gemini_retry,
    with_groq_retry,
    with_retry,
)


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


def _rate_limit_error(message: str, *, retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        headers=headers,
    )
    return RateLimitError(message, response=response, body=None)


def test_groq_retry_delay_parses_message_seconds() -> None:
    exc = _rate_limit_error("Please try again in 4s.")
    assert groq_retry_delay_seconds(exc) == pytest.approx(4.25)


def test_groq_retry_delay_uses_retry_after_header() -> None:
    exc = _rate_limit_error("Rate limit reached", retry_after="2")
    assert groq_retry_delay_seconds(exc) == pytest.approx(2.25)


def test_with_groq_retry_waits_for_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    attempts = {"count": 0}

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("core.retry.time.sleep", fake_sleep)

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _rate_limit_error("Please try again in 1.5s.")
        return "ok"

    result = with_groq_retry(flaky, max_attempts=3, base_delay_seconds=0.01)
    assert result == "ok"
    assert attempts["count"] == 2
    assert sleeps == [pytest.approx(1.75)]


def _resource_exhausted(message: str) -> ResourceExhausted:
    return ResourceExhausted(message)


def test_gemini_retry_delay_parses_message_seconds() -> None:
    exc = _resource_exhausted("Please retry in 25.755784907s.")
    assert gemini_retry_delay_seconds(exc) == pytest.approx(26.005784907)


def test_gemini_is_daily_quota_error_detects_per_day_limit() -> None:
    exc = _resource_exhausted(
        "429 quota exceeded " "GenerateRequestsPerDayPerProjectPerModel-FreeTier limit: 0"
    )
    assert gemini_is_daily_quota_error(exc) is True


def test_gemini_is_daily_quota_error_ignores_rpm_limit() -> None:
    exc = _resource_exhausted(
        "429 quota exceeded " "GenerateRequestsPerMinutePerProjectPerModel-FreeTier limit: 0"
    )
    assert gemini_is_daily_quota_error(exc) is False


def test_with_gemini_retry_waits_for_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    attempts = {"count": 0}

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("core.retry.time.sleep", fake_sleep)

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _resource_exhausted("Please retry in 12s.")
        return "ok"

    result = with_gemini_retry(flaky, max_attempts=3, base_delay_seconds=15.0)
    assert result == "ok"
    assert attempts["count"] == 2
    assert sleeps == [pytest.approx(12.25)]


def test_with_gemini_retry_fails_fast_on_daily_quota() -> None:
    attempts = {"count": 0}

    def always_quota() -> None:
        attempts["count"] += 1
        raise _resource_exhausted("GenerateRequestsPerDayPerProjectPerModel-FreeTier limit: 0")

    with pytest.raises(ResourceExhausted):
        with_gemini_retry(always_quota, max_attempts=4, base_delay_seconds=0.01)

    assert attempts["count"] == 1
