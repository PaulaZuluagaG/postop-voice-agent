"""Auditable call trace logging."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from core.config import Settings, get_settings
from core.models import CallSummary, TraceEvent, TurnRecord


class CallTraceLogger:
    """Persist call events to JSONL files and keep in-memory history."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log_dir = self._settings.calls_log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def log_event(self, call_id: UUID, event_type: str, payload: dict) -> TraceEvent:
        event = TraceEvent(
            event_type=event_type,
            call_id=str(call_id),
            payload=payload,
            timestamp=datetime.utcnow(),
        )
        log_path = self._log_dir / f"{call_id}.jsonl"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        return event

    def log_call_start(
        self,
        call_id: UUID,
        *,
        procedure_scenario: str,
        postop_day: int,
    ) -> None:
        self.log_event(
            call_id,
            "call_start",
            {
                "procedure_scenario": procedure_scenario,
                "postop_day": postop_day,
            },
        )

    def log_turn(self, call_id: UUID, turn: TurnRecord) -> None:
        self.log_event(call_id, "turn", turn.model_dump(mode="json"))

    def log_call_close(self, call_id: UUID, summary: CallSummary) -> None:
        self.log_event(call_id, "call_close", summary.model_dump(mode="json"))

    def read_call_log(self, call_id: UUID) -> list[dict]:
        log_path = self._log_dir / f"{call_id}.jsonl"
        if not log_path.exists():
            return []
        events: list[dict] = []
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                events.append(json.loads(line))
        return events
