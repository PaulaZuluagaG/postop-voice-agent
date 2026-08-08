"""Unit tests for OllamaClient helpers."""

from unittest.mock import MagicMock, patch

from agent.llm.ollama_client import OllamaClient
from core.config import Settings
from core.models import LLMTurnOutput, ResponseCategory


def test_generate_structured_parses_json_response() -> None:
    settings = Settings(
        ollama_model="phi3.5",
        ollama_temperature=0.1,
    )
    client = OllamaClient(settings)
    mock_response = MagicMock()
    mock_response.message.content = (
        '{"categoria":"RESPUESTA_VALIDA","texto_paciente":"Hola",'
        '"pregunta":"¿Cómo está?","fuentes":[]}'
    )

    with patch.object(client._client, "chat", return_value=mock_response) as chat:
        output = client._generate_structured("user prompt", retrieved_chunks=[])

    chat.assert_called_once()
    call_kwargs = chat.call_args.kwargs
    assert call_kwargs["model"] == "phi3.5"
    assert call_kwargs["format"] == "json"
    assert call_kwargs["options"]["temperature"] == 0.1
    assert output.categoria == ResponseCategory.RESPUESTA_VALIDA
    assert isinstance(output, LLMTurnOutput)
