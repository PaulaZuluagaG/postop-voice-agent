"""Tests for graceful Groq rate-limit handling in voice calls."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from groq import RateLimitError

from core.exceptions import LLMRateLimitError
from voice.services.postop_llm import PostOpLLMService


def _rate_limit_error() -> RateLimitError:
    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    return RateLimitError(
        "Rate limit reached for tokens per day (TPD): Limit 100000, Used 96922",
        response=response,
        body=None,
    )


def test_handle_rate_limit_closure_speaks_message_and_closes_call() -> None:
    async def run() -> None:
        orchestrator = MagicMock()
        session = MagicMock()
        session.call_closed = False
        session.turns = []
        session.opening_message = ""
        orchestrator.get_session.return_value = session

        service = PostOpLLMService(orchestrator=orchestrator, call_id=uuid4())
        service._stream_response = AsyncMock()
        stop_called = asyncio.Event()

        async def pipeline_stop() -> None:
            stop_called.set()

        service.bind_pipeline_stop(pipeline_stop)

        with patch("voice.services.postop_llm.asyncio.sleep", new=AsyncMock()):
            await service._handle_rate_limit_closure(
                LLMRateLimitError("Groq streaming failed: quota")
            )

        service._stream_response.assert_awaited_once()
        orchestrator.close_call.assert_called_once_with(service._call_id, reason="llm_rate_limit")
        assert stop_called.is_set()
        assert service.call_ended.is_set()

    asyncio.run(run())


def test_handle_turn_rate_limit_does_not_reraise() -> None:
    async def run() -> None:
        orchestrator = MagicMock()
        session = MagicMock()
        session.call_closed = False
        session.turns = []
        session.opening_message = ""
        orchestrator.get_session.return_value = session

        async def failing_stream(*_args, **_kwargs):
            if False:  # pragma: no cover - async generator
                yield ""
            raise LLMRateLimitError("Groq streaming failed: quota")

        orchestrator.stream_turn_response = failing_stream

        service = PostOpLLMService(orchestrator=orchestrator, call_id=uuid4())
        service._handle_rate_limit_closure = AsyncMock()
        service._opening_ready.set()
        service._opening_sent = True

        from voice.frames import PostOpUserTurnFrame

        frame = PostOpUserTurnFrame(text="Tengo dolor")

        await service._handle_turn(frame, MagicMock())

        service._handle_rate_limit_closure.assert_awaited_once()

    asyncio.run(run())
