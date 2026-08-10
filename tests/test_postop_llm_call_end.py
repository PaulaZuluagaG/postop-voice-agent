"""Tests for clinical call finalization in PostOpLLMService."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

from voice.services.postop_llm import PostOpLLMService


def test_finalize_call_uses_pipeline_stop_when_bound() -> None:
    async def run() -> None:
        orchestrator = MagicMock()
        session = MagicMock()
        session.call_closed = True
        session.turns = []
        orchestrator.get_session.return_value = session

        service = PostOpLLMService(orchestrator=orchestrator, call_id=uuid4())
        stop_called = asyncio.Event()

        async def pipeline_stop() -> None:
            stop_called.set()

        service.bind_pipeline_stop(pipeline_stop)
        await service._finalize_call()

        assert stop_called.is_set()
        assert service.call_ended.is_set()

    asyncio.run(run())
