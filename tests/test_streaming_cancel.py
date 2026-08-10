import asyncio

import pytest

from agent.llm.streaming import GroqStreamingClient
from core.exceptions import LLMCancelledError, LLMError


class _FakeGroqStream:
    def __init__(self, deltas: list[str | None]) -> None:
        self._deltas = deltas

    def __iter__(self):
        return iter(self._deltas)


class _FakeChunk:
    def __init__(self, content: str | None) -> None:
        self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content})()})()]


class _FakeCompletions:
    def __init__(self, stream: _FakeGroqStream) -> None:
        self._stream = stream

    def create(self, **kwargs):
        for delta in self._stream._deltas:
            if delta is None:
                break
            yield _FakeChunk(delta)


class _FakeChat:
    def __init__(self, stream: _FakeGroqStream) -> None:
        self.completions = _FakeCompletions(stream)


class _FakeClient:
    def __init__(self, stream: _FakeGroqStream) -> None:
        self.chat = _FakeChat(stream)


class _FakeGroqClient:
    def __init__(self, stream: _FakeGroqStream) -> None:
        self._client = _FakeClient(stream)

    @staticmethod
    def _parse_json(raw_text: str) -> dict:
        return {"texto_paciente": raw_text, "categoria": "verde", "pregunta": "¿Cómo se siente?"}

    @staticmethod
    def _validate_sources(output, retrieved):
        return output


def test_collect_stream_raises_cancelled_when_interrupted_empty() -> None:
    client = GroqStreamingClient(groq_client=_FakeGroqClient(_FakeGroqStream([])))
    cancel = asyncio.Event()
    cancel.set()

    with pytest.raises(LLMCancelledError):
        client._collect_stream_sync("prompt", [], lambda _token: None, cancel)


def test_collect_stream_raises_on_genuine_empty_response() -> None:
    client = GroqStreamingClient(groq_client=_FakeGroqClient(_FakeGroqStream([])))

    with pytest.raises(LLMError, match="respuesta vacía"):
        client._collect_stream_sync("prompt", [], lambda _token: None, None)
