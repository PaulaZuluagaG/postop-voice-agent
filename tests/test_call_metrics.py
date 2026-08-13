"""Tests for call metrics aggregation."""

from __future__ import annotations

import pytest

from agent.metrics.aggregation import (
    aggregate_call_usage,
    latency_percentile,
    per_turn_usage_summary,
    summarize_voice_latencies,
)
from agent.metrics.cost import estimate_call_cost_usd
from core.models import LLMUsage, TurnRecord, TurnTimings


def _turn(
    *,
    prompt: int,
    completion: int,
    total_ms: float,
    voice_ms: float = 0.0,
) -> TurnRecord:
    return TurnRecord(
        turn_number=1,
        patient_input="test",
        agent_response="ok",
        rag_query="q",
        timings=TurnTimings(total_ms=total_ms, voice_response_ms=voice_ms),
        llm_usage=LLMUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        ),
    )


def test_latency_percentile() -> None:
    values = [100.0, 200.0, 300.0, 400.0, 500.0]
    assert latency_percentile(values, 50) == 300.0
    assert latency_percentile(values, 95) == pytest.approx(480.0)


def test_aggregate_call_usage() -> None:
    turns = [
        _turn(prompt=1000, completion=200, total_ms=800),
        _turn(prompt=900, completion=150, total_ms=700),
    ]
    usage = aggregate_call_usage(turns)
    assert usage.llm_invocations == 2
    assert usage.rag_queries == 2
    assert usage.prompt_tokens == 1900
    assert usage.completion_tokens == 350


def test_summarize_voice_latencies() -> None:
    turns = [
        _turn(prompt=1, completion=1, total_ms=1, voice_ms=1200),
        _turn(prompt=1, completion=1, total_ms=1, voice_ms=1800),
    ]
    summary = summarize_voice_latencies(turns)
    assert summary["samples"] == 2
    assert summary["p50_ms"] == 1500.0


def test_estimate_call_cost_usd() -> None:
    usage = aggregate_call_usage([_turn(prompt=10_000, completion=2_000, total_ms=1)])
    cost = estimate_call_cost_usd(usage, estimated_call_minutes=4.0)
    assert cost.total_usd > 0
    assert "Groq" in cost.assumptions


def test_per_turn_usage_summary() -> None:
    summary = per_turn_usage_summary([_turn(prompt=1000, completion=100, total_ms=500)])
    assert summary["avg_prompt_tokens"] == 1000.0
    assert summary["avg_rag_queries"] == 1.0
