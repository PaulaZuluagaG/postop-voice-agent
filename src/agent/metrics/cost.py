"""Estimated production cost per call (API pricing extrapolation)."""

from __future__ import annotations

from dataclasses import dataclass

from core.models import CallUsageMetrics

# Published list prices (USD) — adjust if providers change tariffs.
GROQ_INPUT_USD_PER_M = 0.59
GROQ_OUTPUT_USD_PER_M = 0.79
DEEPGRAM_USD_PER_MINUTE = 0.0058


@dataclass(frozen=True)
class CallCostEstimate:
    groq_usd: float
    deepgram_usd: float
    total_usd: float
    assumptions: str


def estimate_call_cost_usd(
    usage: CallUsageMetrics,
    *,
    estimated_call_minutes: float = 4.0,
    opening_rag_queries: int = 1,
) -> CallCostEstimate:
    """Extrapolate per-call cost using Groq token usage and Deepgram STT duration."""
    groq_usd = (
        usage.prompt_tokens / 1_000_000 * GROQ_INPUT_USD_PER_M
        + usage.completion_tokens / 1_000_000 * GROQ_OUTPUT_USD_PER_M
    )
    deepgram_usd = estimated_call_minutes * DEEPGRAM_USD_PER_MINUTE
    assumptions = (
        f"Groq Llama 3.1 70B @ ${GROQ_INPUT_USD_PER_M}/M in + "
        f"${GROQ_OUTPUT_USD_PER_M}/M out; Deepgram @ ${DEEPGRAM_USD_PER_MINUTE}/min "
        f"for ~{estimated_call_minutes:.1f} min STT; "
        f"{usage.llm_invocations} LLM calls, {usage.rag_queries + opening_rag_queries} RAG queries "
        f"(incl. opening)."
    )
    return CallCostEstimate(
        groq_usd=round(groq_usd, 5),
        deepgram_usd=round(deepgram_usd, 5),
        total_usd=round(groq_usd + deepgram_usd, 5),
        assumptions=assumptions,
    )
