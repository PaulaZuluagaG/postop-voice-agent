"""Regression tests for patient-facing session summary endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from voice.web_server import create_app


def test_session_summary_route_is_not_shadowed_by_proxy() -> None:
    app = create_app()
    client = TestClient(app)

    start = client.post("/start", json={"body": {"patientName": "Test"}})
    assert start.status_code == 200
    session_id = start.json()["sessionId"]

    response = client.get(f"/sessions/{session_id}/summary")
    assert response.status_code == 404
    assert response.json()["detail"] == "Resumen aún no disponible"
    assert response.json()["detail"] != "Ruta no soportada"
