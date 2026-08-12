from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from voice.services.postop_llm import PostOpLLMService


def test_ensure_opening_is_idempotent() -> None:
    async def fake_opening(_call_id):
        yield "Hola. "
        yield "¿Cómo está?"

    async def run() -> None:
        orchestrator = MagicMock()
        session = MagicMock()
        session.call_closed = False
        session.opening_message = "Hola. ¿Cómo está?"
        session.turns = []
        orchestrator.get_session.return_value = session
        orchestrator.stream_opening_response = fake_opening

        service = PostOpLLMService(
            orchestrator=orchestrator,
            call_id=uuid4(),
            defer_opening_until_connected=True,
        )
        service._stream_response = AsyncMock()
        service._wait_opening_playback_grace = AsyncMock()

        await service.ensure_opening()
        await service.ensure_opening()

        assert service._opening_sent is True
        assert service._stream_response.await_count == 1
        assert service._opening_ready.is_set()

    asyncio.run(run())


def test_user_turn_during_opening_is_ignored() -> None:
    async def run() -> None:
        orchestrator = MagicMock()
        session = MagicMock()
        session.call_closed = False
        session.opening_message = None
        session.turns = []
        orchestrator.get_session.return_value = session
        orchestrator.stream_turn_response = MagicMock()

        service = PostOpLLMService(
            orchestrator=orchestrator,
            call_id=uuid4(),
            defer_opening_until_connected=True,
        )
        service._opening_in_progress = True

        from voice.frames import PostOpUserTurnFrame

        await service._handle_turn(PostOpUserTurnFrame(text=" eco del agente "), MagicMock())

        orchestrator.stream_turn_response.assert_not_called()

    asyncio.run(run())
