"""Unit tests for GroqClient helpers."""

from unittest.mock import MagicMock, patch

from agent.llm.groq_client import GroqClient
from core.config import Settings
from core.models import LLMTurnOutput, ProcedureScenario, ResponseCategory


def test_generate_structured_parses_json_response() -> None:
    settings = Settings(
        groq_api_key="test-key",
        groq_model="llama-3.1-70b-versatile",
        groq_temperature=0.1,
    )
    client = GroqClient(settings)
    mock_choice = MagicMock()
    mock_choice.message.content = (
        '{"categoria":"RESPUESTA_VALIDA","texto_paciente":"Hola",'
        '"pregunta":"¿Cómo está?","fuentes":[]}'
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(
        client._client.chat.completions, "create", return_value=mock_response
    ) as create:
        output = client._generate_structured("user prompt", retrieved_chunks=[])

    create.assert_called_once()
    call_kwargs = create.call_args.kwargs
    assert call_kwargs["model"] == "llama-3.1-70b-versatile"
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["temperature"] == 0.1
    assert output.categoria == ResponseCategory.RESPUESTA_VALIDA
    assert isinstance(output, LLMTurnOutput)


def test_validate_document_category_accepts_match() -> None:
    settings = Settings(groq_api_key="test-key")
    client = GroqClient(settings)
    mock_choice = MagicMock()
    mock_choice.message.content = (
        '{"coincide": true, "tema_detectado": "apendicitis", "motivo": "Coincide"}'
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        matches, message = client.validate_document_category(
            document_excerpt="Guía de apendicitis aguda",
            procedure_scenario=ProcedureScenario.APPENDICITIS,
        )

    assert matches is True
    assert message == "Coincide"
