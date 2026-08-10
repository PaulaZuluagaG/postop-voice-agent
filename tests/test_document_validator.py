"""Unit tests for Gemini document validation."""

from unittest.mock import patch

from agent.llm.document_validator import DocumentValidator
from core.config import Settings
from core.models import ProcedureScenario


def test_validate_document_category_accepts_match() -> None:
    settings = Settings(gemini_api_key="test-key")
    validator = DocumentValidator(settings)

    with patch.object(
        validator._gemini,
        "generate_json",
        return_value={
            "coincide": True,
            "tema_detectado": "apendicitis",
            "motivo": "Coincide",
        },
    ) as generate_json:
        matches, message = validator.validate_document_category(
            document_excerpt="Guía de apendicitis aguda",
            procedure_scenario=ProcedureScenario.APPENDICITIS,
        )

    generate_json.assert_called_once()
    assert matches is True
    assert message == "Coincide"
