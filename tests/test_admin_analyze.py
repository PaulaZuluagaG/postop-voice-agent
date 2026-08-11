from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import ResourceExhausted

from api.auth import require_admin_token
from api.main import create_app
from api.services.documents import get_document_service
from core.exceptions import LLMError, PostOpError


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[require_admin_token] = lambda: None
    service = MagicMock()
    app.dependency_overrides[get_document_service] = lambda: service
    test_client = TestClient(app)
    test_client._service = service  # type: ignore[attr-defined]
    yield test_client
    app.dependency_overrides.clear()


def test_analyze_document_maps_gemini_quota_to_502(client: TestClient) -> None:
    client._service.analyze_document.side_effect = ResourceExhausted(
        "GenerateRequestsPerDayPerProjectPerModel-FreeTier limit: 0"
    )

    response = client.post(
        "/admin/documents/analyze",
        files={"file": ("cataratas.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 502
    assert "Cuota diaria de Gemini" in response.json()["detail"]


def test_analyze_document_maps_postop_error_to_502(client: TestClient) -> None:
    client._service.analyze_document.side_effect = PostOpError(
        "gemini_suggest_procedure failed after 3 attempts"
    )

    response = client.post(
        "/admin/documents/analyze",
        files={"file": ("cataratas.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 502
    assert "failed after 3 attempts" in response.json()["detail"]


def test_analyze_document_maps_llm_error_to_502(client: TestClient) -> None:
    client._service.analyze_document.side_effect = LLMError(
        "GEMINI_API_KEY is required for Gemini LLM operations"
    )

    response = client.post(
        "/admin/documents/analyze",
        files={"file": ("cataratas.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 502
    assert "GEMINI_API_KEY" in response.json()["detail"]
