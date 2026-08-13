"""Aggregate per-turn metrics into call-level summaries."""

from __future__ import annotations

import math
from statistics import median

from core.models import CallUsageMetrics, TurnRecord


def latency_percentile(values: list[float], percentile: float) -> float:
    """Return the given percentile (0–100) with linear interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (percentile / 100) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def aggregate_call_usage(turns: list[TurnRecord]) -> CallUsageMetrics:
    """Sum LLM/RAG consumption across patient turns."""
    metrics = CallUsageMetrics()
    for turn in turns:
        metrics.llm_invocations += turn.llm_invocations
        metrics.rag_queries += turn.rag_queries
        if turn.llm_usage is not None:
            metrics.prompt_tokens += turn.llm_usage.prompt_tokens
            metrics.completion_tokens += turn.llm_usage.completion_tokens
            metrics.total_tokens += turn.llm_usage.total_tokens
    return metrics


def summarize_voice_latencies(turns: list[TurnRecord]) -> dict[str, float | int]:
    """Summarize end-to-end voice latencies recorded on turns."""
    values = [
        turn.timings.voice_response_ms for turn in turns if turn.timings.voice_response_ms > 0
    ]
    if not values:
        return {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0}

    return {
        "samples": len(values),
        "p50_ms": round(latency_percentile(values, 50), 1),
        "p95_ms": round(latency_percentile(values, 95), 1),
        "mean_ms": round(sum(values) / len(values), 1),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
        "median_ms": round(median(values), 1),
    }


def per_turn_usage_summary(turns: list[TurnRecord]) -> dict[str, float | int]:
    """Average token and invocation counts per patient turn."""
    if not turns:
        return {
            "turns": 0,
            "avg_prompt_tokens": 0.0,
            "avg_completion_tokens": 0.0,
            "avg_total_tokens": 0.0,
            "avg_llm_invocations": 0.0,
            "avg_rag_queries": 0.0,
        }

    usage = aggregate_call_usage(turns)
    count = len(turns)
    return {
        "turns": count,
        "avg_prompt_tokens": round(usage.prompt_tokens / count, 1),
        "avg_completion_tokens": round(usage.completion_tokens / count, 1),
        "avg_total_tokens": round(usage.total_tokens / count, 1),
        "avg_llm_invocations": round(usage.llm_invocations / count, 2),
        "avg_rag_queries": round(usage.rag_queries / count, 2),
    }
