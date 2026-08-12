"""Auditable call trace logging."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from core.config import Settings, get_settings
from core.models import CallSummary, TraceEvent, TurnRecord

SUMMARY_LOG_NAME = "events.json"
JSON_INDENT = 2


class CallTraceLogger:
    """Persist call events under per-call folders with turn and summary logs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log_dir = self._settings.calls_log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def call_root(self, call_id: UUID) -> Path:
        return self._log_dir / str(call_id)

    def summary_log_path(self, call_id: UUID) -> Path:
        return self.call_root(call_id) / "summary" / SUMMARY_LOG_NAME

    def turn_log_path(self, call_id: UUID, turn_number: int) -> Path:
        return self.call_root(call_id) / "turns" / f"turn_{turn_number:03d}.json"

    def _ensure_call_dirs(self, call_id: UUID) -> tuple[Path, Path]:
        root = self.call_root(call_id)
        turns_dir = root / "turns"
        summary_dir = root / "summary"
        turns_dir.mkdir(parents=True, exist_ok=True)
        summary_dir.mkdir(parents=True, exist_ok=True)
        return turns_dir, summary_dir

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=JSON_INDENT, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _append_summary_event(self, log_path: Path, event: TraceEvent) -> None:
        events = self._read_summary_events(log_path)
        events.append(event.model_dump(mode="json"))
        self._write_json(log_path, events)

    def log_event(self, call_id: UUID, event_type: str, payload: dict) -> TraceEvent:
        self._ensure_call_dirs(call_id)
        event = TraceEvent(
            event_type=event_type,
            call_id=str(call_id),
            payload=payload,
            timestamp=datetime.utcnow(),
        )
        self._append_summary_event(self.summary_log_path(call_id), event)
        return event

    def log_call_start(
        self,
        call_id: UUID,
        *,
        procedure_id: str,
        procedure_scenario: str,
        postop_day: int,
        patient_name: str | None = None,
        patient_id: str | None = None,
        procedure_name: str | None = None,
        surgery_date: str | None = None,
        protocol_used: str | None = None,
        custom_procedure: str | None = None,
        uses_general_protocol: bool = False,
        patient_comorbidities: list[str] | None = None,
    ) -> None:
        payload: dict[str, str | int | bool | list[str]] = {
            "procedure_id": procedure_id,
            "procedure_scenario": procedure_scenario,
            "postop_day": postop_day,
            "uses_general_protocol": uses_general_protocol,
        }
        if patient_comorbidities:
            payload["patient_comorbidities"] = patient_comorbidities
        if patient_name:
            payload["patient_name"] = patient_name
        if patient_id:
            payload["patient_id"] = patient_id
        if procedure_name:
            payload["procedure_name"] = procedure_name
        if surgery_date:
            payload["surgery_date"] = surgery_date
        if protocol_used:
            payload["protocol_used"] = protocol_used
        if custom_procedure:
            payload["custom_procedure"] = custom_procedure
        self.log_event(call_id, "call_start", payload)

    def log_turn(self, call_id: UUID, turn: TurnRecord) -> None:
        self._ensure_call_dirs(call_id)
        event = TraceEvent(
            event_type="turn",
            call_id=str(call_id),
            payload=turn.model_dump(mode="json"),
            timestamp=datetime.utcnow(),
        )
        self._write_json(
            self.turn_log_path(call_id, turn.turn_number),
            event.model_dump(mode="json"),
        )

    def log_call_close(self, call_id: UUID, summary: CallSummary) -> None:
        self.log_event(call_id, "call_close", summary.model_dump(mode="json"))

    def read_call_log(self, call_id: UUID) -> list[dict]:
        legacy_path = self._log_dir / f"{call_id}.jsonl"
        if legacy_path.exists():
            return self._read_jsonl(legacy_path)

        root = self.call_root(call_id)
        if not root.exists():
            return []

        events: list[dict] = []
        summary_path = self.summary_log_path(call_id)
        legacy_summary_path = summary_path.with_suffix(".jsonl")
        if summary_path.exists():
            events.extend(self._read_summary_events(summary_path))
        elif legacy_summary_path.exists():
            events.extend(self._read_jsonl(legacy_summary_path))

        turns_dir = root / "turns"
        if turns_dir.exists():
            turn_paths = sorted(turns_dir.glob("turn_*.json"))
            turn_paths.extend(sorted(turns_dir.glob("turn_*.jsonl")))
            seen: set[Path] = set()
            for turn_path in turn_paths:
                if turn_path in seen:
                    continue
                seen.add(turn_path)
                events.extend(self._read_turn_file(turn_path))

        events.sort(key=lambda item: item.get("timestamp", ""))
        return events

    @staticmethod
    def _read_summary_events(path: Path) -> list[dict]:
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return [payload]
        return []

    @staticmethod
    def _read_turn_file(path: Path) -> list[dict]:
        if path.suffix == ".jsonl":
            return CallTraceLogger._read_jsonl(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        events: list[dict] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
