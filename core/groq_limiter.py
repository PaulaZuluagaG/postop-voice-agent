"""Serialize Groq API calls to avoid overlapping requests in one process."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_groq_call_lock = threading.Lock()


@contextmanager
def groq_call_slot() -> Iterator[None]:
    """Hold a process-wide lock while a Groq request is in flight."""
    with _groq_call_lock:
        yield
