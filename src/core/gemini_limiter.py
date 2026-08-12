"""Serialize Gemini batch API calls (protocols + ingest validation)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_gemini_call_lock = threading.Lock()


@contextmanager
def gemini_call_slot() -> Iterator[None]:
    """Hold a process-wide lock while a Gemini batch request is in flight."""
    with _gemini_call_lock:
        yield
