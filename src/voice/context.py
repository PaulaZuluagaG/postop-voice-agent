"""Voice pipeline context shared across Pipecat processors."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

current_call_id: ContextVar[UUID | None] = ContextVar("current_call_id", default=None)
