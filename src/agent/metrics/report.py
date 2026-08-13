"""Analyze call logs and build README-ready metric reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.metrics.aggregation import (
    aggregate_call_usage,
    latency_percentile,
    per_turn_usage_summary,
    summarize_voice_latencies,
)
from agent.metrics.cost import estimate_call_cost_usd
from core.models import CallSummary, TurnRecord


@dataclass(frozen=True)
class MetricsReport:
    generated_at: str
    source: str
    calls_analyzed: int
    turns_analyzed: int
    voice_latency: dict[str, float | int]
    orchestrator_latency_ms: dict[str, float | int]
    per_turn: dict[str, float | int]
    per_call: dict[str, float | int]
    cost_estimate_usd: dict[str, float | str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "source": self.source,
            "calls_analyzed": self.calls_analyzed,
            "turns_analyzed": self.turns_analyzed,
            "voice_latency": self.voice_latency,
            "orchestrator_latency_ms": self.orchestrator_latency_ms,
            "per_turn": self.per_turn,
            "per_call": self.per_call,
            "cost_estimate_usd": self.cost_estimate_usd,
        }


def _load_turn_files(turns_dir: Path) -> list[TurnRecord]:
    turns: list[TurnRecord] = []
    for path in sorted(turns_dir.glob("turn_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        turn_payload = payload.get("payload", payload)
        turns.append(TurnRecord.model_validate(turn_payload))
    return turns


def _load_summary_events(summary_path: Path) -> list[dict[str, Any]]:
    if not summary_path.is_file():
        return []
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return [data]


def collect_turns_from_logs(log_dir: Path) -> list[TurnRecord]:
    turns: list[TurnRecord] = []
    if not log_dir.is_dir():
        return turns
    for call_dir in sorted(log_dir.iterdir()):
        turns_dir = call_dir / "turns"
        if turns_dir.is_dir():
            turns.extend(_load_turn_files(turns_dir))
    return turns


def summarize_orchestrator_latencies(turns: list[TurnRecord]) -> dict[str, float | int]:
    totals = [turn.timings.total_ms for turn in turns if turn.timings.total_ms > 0]
    first_tokens = [
        turn.timings.first_token_ms for turn in turns if turn.timings.first_token_ms > 0
    ]
    if not totals:
        return {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0}
    return {
        "samples": len(totals),
        "p50_ms": round(latency_percentile(totals, 50), 1),
        "p95_ms": round(latency_percentile(totals, 95), 1),
        "first_token_p50_ms": round(latency_percentile(first_tokens, 50), 1)
        if first_tokens
        else 0.0,
        "first_token_p95_ms": round(latency_percentile(first_tokens, 95), 1)
        if first_tokens
        else 0.0,
    }


def build_report_from_turns(
    turns: list[TurnRecord],
    *,
    source: str,
    calls_analyzed: int = 1,
) -> MetricsReport:
    usage = aggregate_call_usage(turns)
    voice = summarize_voice_latencies(turns)
    orchestrator = summarize_orchestrator_latencies(turns)
    per_turn = per_turn_usage_summary(turns)
    cost = estimate_call_cost_usd(usage)

    per_call = {
        "avg_llm_invocations": round(usage.llm_invocations / max(calls_analyzed, 1), 1),
        "avg_rag_queries": round(usage.rag_queries / max(calls_analyzed, 1), 1),
        "avg_prompt_tokens": round(usage.prompt_tokens / max(calls_analyzed, 1), 1),
        "avg_completion_tokens": round(usage.completion_tokens / max(calls_analyzed, 1), 1),
        "avg_total_tokens": round(usage.total_tokens / max(calls_analyzed, 1), 1),
    }

    return MetricsReport(
        generated_at=datetime.now(tz=UTC).isoformat(),
        source=source,
        calls_analyzed=calls_analyzed,
        turns_analyzed=len(turns),
        voice_latency=voice,
        orchestrator_latency_ms=orchestrator,
        per_turn=per_turn,
        per_call=per_call,
        cost_estimate_usd={
            "groq_usd": cost.groq_usd,
            "deepgram_usd": cost.deepgram_usd,
            "total_usd": cost.total_usd,
            "assumptions": cost.assumptions,
        },
    )


def build_report_from_logs(log_dir: Path) -> MetricsReport:
    turns = collect_turns_from_logs(log_dir)
    call_dirs = (
        [path for path in log_dir.iterdir() if (path / "turns").is_dir()]
        if log_dir.is_dir()
        else []
    )
    return build_report_from_turns(
        turns,
        source=f"logs:{log_dir}",
        calls_analyzed=max(len(call_dirs), 1),
    )


def write_report(path: Path, report: MetricsReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def summary_from_orchestrator(summary: CallSummary, *, source: str) -> MetricsReport:
    return build_report_from_turns(summary.turn_history, source=source)
