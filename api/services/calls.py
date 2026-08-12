"""Read persisted call summaries from trace logs."""

from __future__ import annotations

import json
from pathlib import Path

from agent.decision.clinical_summary import (
    format_sources_used_text,
    replace_clinical_summary_sources,
    resolve_source_labels,
)
from core.config import Settings, get_settings
from core.models import CallSummary


class CallLogService:
    """Load call summaries from logs/calls/*/summary/events.json."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log_dir = self._settings.calls_log_dir

    def list_recent_calls(self, *, limit: int = 50) -> list[dict]:
        if not self._log_dir.exists():
            return []

        entries: list[dict] = []
        for call_dir in self._log_dir.iterdir():
            if not call_dir.is_dir():
                continue
            summary_path = call_dir / "summary" / "events.json"
            if not summary_path.exists():
                continue
            try:
                item = self._summary_list_item(call_dir.name, summary_path)
            except (json.JSONDecodeError, OSError, ValueError):
                continue
            if item is not None:
                entries.append(item)

        entries.sort(key=lambda row: row.get("closed_at") or "", reverse=True)
        return entries[:limit]

    def get_call_summary(self, call_id: str) -> CallSummary | None:
        summary_path = self._log_dir / call_id / "summary" / "events.json"
        if not summary_path.exists():
            return None
        payload = self._extract_call_close_payload(summary_path)
        if payload is None:
            return None
        return self._with_readable_sources(CallSummary.model_validate(payload))

    def _with_readable_sources(self, summary: CallSummary) -> CallSummary:
        if not summary.sources_used or not summary.clinical_summary:
            return summary

        labels = resolve_source_labels(summary.sources_used, settings=self._settings)
        sources_text = format_sources_used_text(summary.sources_used, source_labels=labels)
        updated = replace_clinical_summary_sources(summary.clinical_summary, sources_text)
        if updated == summary.clinical_summary:
            return summary
        return summary.model_copy(update={"clinical_summary": updated})

    @staticmethod
    def _extract_call_close_payload(summary_path: Path) -> dict | None:
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return None
        for event in reversed(raw):
            if isinstance(event, dict) and event.get("event_type") == "call_close":
                payload = event.get("payload")
                if isinstance(payload, dict):
                    return payload
        return None

    def _summary_list_item(self, call_id: str, summary_path: Path) -> dict | None:
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return None

        call_start: dict | None = None
        call_close: dict | None = None
        closed_at: str | None = None
        for event in raw:
            if not isinstance(event, dict):
                continue
            if event.get("event_type") == "call_start":
                call_start = (
                    event.get("payload") if isinstance(event.get("payload"), dict) else None
                )
            if event.get("event_type") == "call_close":
                call_close = (
                    event.get("payload") if isinstance(event.get("payload"), dict) else None
                )
                closed_at = str(event.get("timestamp") or "")

        if call_close is None:
            return None

        return {
            "call_id": call_id,
            "patient_name": call_close.get("patient_name")
            or (call_start or {}).get("patient_name")
            or "Paciente",
            "patient_id": call_close.get("patient_id") or (call_start or {}).get("patient_id"),
            "procedure_id": call_close.get("procedure_id"),
            "postop_day": call_close.get("postop_day"),
            "decision_label": call_close.get("decision_label")
            or call_close.get("severity")
            or "verde",
            "final_score": call_close.get("final_score", 0),
            "closed_reason": call_close.get("closed_reason"),
            "closed_at": closed_at,
            "turn_count": call_close.get("turn_count", 0),
        }
