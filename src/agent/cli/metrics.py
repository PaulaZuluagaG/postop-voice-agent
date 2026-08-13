"""CLI: benchmark calls and report mandatory README metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.metrics.aggregation import latency_percentile
from agent.metrics.report import build_report_from_logs, build_report_from_turns, write_report
from agent.orchestrator import ConversationOrchestrator
from core.config import get_settings
from core.exceptions import ConfigurationError, PostOpError
from core.models import ProcedureScenario
from knowledge.ingest.shared_embedder import warmup_embedding_service
from knowledge.retrieval.retriever import ContextualRetriever

DEFAULT_TURNS = [
    "Hola, me siento un poco cansada pero bien en general.",
    "Me duele la herida, diría que un 4 de 10.",
    "Tengo 37.8 de temperatura, la medí hace un rato.",
    "La herida se ve un poco enrojecida alrededor.",
    "He podido caminar un poco por la casa.",
]


def _run_simulated_call(
    orchestrator: ConversationOrchestrator,
    *,
    procedure: ProcedureScenario,
    postop_day: int,
    messages: list[str],
) -> list:
    session = orchestrator.start_call(
        procedure_scenario=procedure,
        postop_day=postop_day,
        patient_name="Paula Demo",
        patient_id="demo-metrics",
    )
    for message in messages:
        orchestrator.process_turn(session.call_id, message)
        session = orchestrator.get_session(session.call_id)
        if session.call_closed:
            break
    summary = orchestrator.close_call(session.call_id)
    return summary.turn_history


def _benchmark_retrieval(
    retriever: ContextualRetriever,
    *,
    procedure_id: str,
    messages: list[str],
) -> list[float]:
    latencies: list[float] = []
    for message in messages:
        _query, _chunks, retrieval_ms = retriever.retrieve(
            message,
            procedure_id=procedure_id,
            postop_day=3,
        )
        latencies.append(retrieval_ms)
    return latencies


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure and report call latency, token usage, and cost metrics.",
    )
    parser.add_argument(
        "--logs",
        type=Path,
        default=None,
        help="Analyze existing call logs instead of running a live benchmark.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/metrics/call-metrics.json"),
        help="JSON report output path.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=2,
        help="Simulated calls when benchmarking live (requires GROQ + Qdrant).",
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Measure RAG retrieval latency only (no Groq tokens).",
    )
    args = parser.parse_args()
    settings = get_settings()

    if args.retrieval_only:
        warmup_embedding_service(settings)
        retriever = ContextualRetriever(settings)
        latencies = _benchmark_retrieval(
            retriever,
            procedure_id="appendicitis",
            messages=DEFAULT_TURNS,
        )
        payload = {
            "mode": "retrieval_only",
            "samples": len(latencies),
            "p50_ms": round(latency_percentile(latencies, 50), 1),
            "p95_ms": round(latency_percentile(latencies, 95), 1),
            "mean_ms": round(sum(latencies) / len(latencies), 1),
            "values_ms": [round(item, 1) for item in latencies],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.logs:
        report = build_report_from_logs(args.logs)
        write_report(args.output, report)
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return

    if not settings.groq_api_key:
        raise ConfigurationError("GROQ_API_KEY is required for live benchmarking.")

    warmup_embedding_service(settings)
    orchestrator = ConversationOrchestrator(settings=settings)
    all_turns = []
    for index in range(args.runs):
        postop_day = 3 if index % 2 == 0 else 7
        turns = _run_simulated_call(
            orchestrator,
            procedure=ProcedureScenario.APPENDICITIS,
            postop_day=postop_day,
            messages=DEFAULT_TURNS,
        )
        all_turns.extend(turns)

    report = build_report_from_turns(
        all_turns,
        source=f"benchmark:{args.runs}x appendicitis (Groq + Qdrant)",
        calls_analyzed=args.runs,
    )
    write_report(args.output, report)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ConfigurationError, PostOpError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
