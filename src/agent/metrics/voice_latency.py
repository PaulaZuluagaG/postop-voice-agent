"""Track voice turn latency: patient turn ready → first TTS audio."""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock
from uuid import UUID

VoiceTimingsHandler = Callable[[float, float | None], None]


class VoiceLatencyTracker:
    """Per-call timestamps for end-to-end voice response measurement."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._turn_started_at: dict[str, float] = {}
        self._tts_started_at: dict[str, float] = {}
        self._handlers: dict[str, VoiceTimingsHandler] = {}

    def register_handler(self, call_id: UUID, handler: VoiceTimingsHandler) -> None:
        with self._lock:
            self._handlers[str(call_id)] = handler

    def unregister_handler(self, call_id: UUID) -> None:
        with self._lock:
            self._handlers.pop(str(call_id), None)

    def begin_turn(self, call_id: UUID) -> None:
        with self._lock:
            self._turn_started_at[str(call_id)] = time.perf_counter()

    def begin_tts(self, call_id: UUID) -> None:
        with self._lock:
            self._tts_started_at[str(call_id)] = time.perf_counter()

    def mark_first_audio(self, call_id: UUID) -> None:
        with self._lock:
            key = str(call_id)
            started = self._turn_started_at.pop(key, None)
            tts_started = self._tts_started_at.pop(key, None)
            if started is None:
                return
            voice_ms = (time.perf_counter() - started) * 1000
            tts_ms = (time.perf_counter() - tts_started) * 1000 if tts_started is not None else None
            handler = self._handlers.get(key)
            if handler is not None:
                handler(voice_ms, tts_ms)


voice_latency_tracker = VoiceLatencyTracker()
