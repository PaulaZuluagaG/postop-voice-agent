"""Tests for duplicate turn protection in PostOpLLMService."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock
from uuid import uuid4

from voice.frames import PostOpUserTurnFrame
from voice.services.postop_llm import PostOpLLMService


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.stream_calls = 0
        self._session = MagicMock()
        self._session.call_closed = False
        self._session.turns = []

    def get_session(self, _call_id):
        return self._session

    async def stream_turn_response(
        self,
        _call_id,
        _patient_message: str,
        *,
        cancel_event=None,
    ) -> AsyncIterator[str]:
        self.stream_calls += 1
        yield "Hola"


def test_duplicate_patient_message_is_ignored() -> None:
    async def run() -> None:
        orchestrator = _FakeOrchestrator()
        service = PostOpLLMService(orchestrator=orchestrator, call_id=uuid4())

        frame = PostOpUserTurnFrame(text="Me duele un poco")

        await service._handle_turn(frame, MagicMock())
        await service._handle_turn(frame, MagicMock())

        assert orchestrator.stream_calls == 1

    asyncio.run(run())


def test_concurrent_turn_is_ignored_while_generation_runs() -> None:
    async def run() -> None:
        orchestrator = _FakeOrchestrator()
        service = PostOpLLMService(orchestrator=orchestrator, call_id=uuid4())
        started = asyncio.Event()
        release = asyncio.Event()
        stream_attempts = {"count": 0}

        async def slow_stream(_token_source: AsyncIterator[str]) -> None:
            stream_attempts["count"] += 1

            async def run_generation() -> None:
                started.set()
                await release.wait()

            service._active_task = asyncio.create_task(run_generation())
            try:
                await service._active_task
            finally:
                service._active_task = None

        service._stream_response = slow_stream  # type: ignore[method-assign]

        frame_a = PostOpUserTurnFrame(text="Primera pregunta")
        frame_b = PostOpUserTurnFrame(text="Segunda pregunta")

        first = asyncio.create_task(service._handle_turn(frame_a, MagicMock()))
        await started.wait()
        await service._handle_turn(frame_b, MagicMock())
        release.set()
        await first

        assert stream_attempts["count"] == 1

    asyncio.run(run())
