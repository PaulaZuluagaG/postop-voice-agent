"""Servidor FastAPI WebRTC para la app de voz María."""

# ruff: noqa: E402

from __future__ import annotations

import uuid
from typing import Any

from core.ssl_certs import configure_ssl_certificates

configure_ssl_certificates()

import uvicorn  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from loguru import logger  # noqa: E402
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection  # noqa: E402
from pipecat.transports.smallwebrtc.request_handler import (  # noqa: E402
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.workers.runner import WorkerRunner  # noqa: E402

from agent.traceability.calls import CallLogService
from core.config import Settings, get_settings
from core.exceptions import ConfigurationError
from core.registration import registration_from_frontend
from core.scenarios import list_procedure_options_from_disk, resolve_procedure_selection
from knowledge.protocol.loader import list_risk_factors_for_procedure
from voice.browser import build_webrtc_pipeline
from voice.pipeline import create_orchestrator_and_session


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="María · Agente de voz postoperatorio",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.voice_web_cors_origins,
        allow_origin_regex=settings.voice_web_cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    active_sessions: dict[str, dict[str, Any]] = {}
    session_call_ids: dict[str, str] = {}
    webrtc_handler = SmallWebRTCRequestHandler()

    @app.get("/status")
    async def status() -> dict[str, str]:
        return {"status": "ready", "transport": "webrtc"}

    @app.get("/api/procedures")
    def list_procedures() -> list[dict[str, str]]:
        return [
            {"value": value, "label": label}
            for value, label in list_procedure_options_from_disk(settings.textos_dir)
        ]

    @app.get("/api/procedures/{procedure_id}/risk-factors")
    def list_procedure_risk_factors(procedure_id: str) -> list[dict[str, str]]:
        selection = resolve_procedure_selection(procedure_id)
        if selection.is_other:
            return []
        return list_risk_factors_for_procedure(
            selection.procedure_id,
            settings=settings,
            uses_general_protocol=selection.uses_general_protocol,
        )

    @app.post("/start")
    async def start_agent(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        session_id = str(uuid.uuid4())
        active_sessions[session_id] = payload.get("body") or payload

        result: dict[str, Any] = {"sessionId": session_id}
        if payload.get("enableDefaultIceServers"):
            result["iceConfig"] = {
                "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}],
            }
        return result

    async def _run_voice_session(
        connection: SmallWebRTCConnection,
        patient_payload: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        registration = registration_from_frontend(patient_payload)
        orchestrator, call_id = create_orchestrator_and_session(registration, settings=settings)
        if session_id:
            session_call_ids[session_id] = str(call_id)
        voice_session = build_webrtc_pipeline(
            orchestrator,
            call_id,
            connection,
            settings=settings,
        )
        transport = voice_session.transport
        if transport is None:
            raise RuntimeError("Transporte WebRTC no disponible")

        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(voice_session.worker)

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(_transport: Any, _client: Any) -> None:
            logger.info("Cliente WebRTC desconectado: {}", call_id)
            session = orchestrator.get_session(call_id)
            if not session.call_closed:
                orchestrator.close_call(call_id, reason="client_disconnect")
            await runner.cancel()

        try:
            await runner.run()
        finally:
            session = orchestrator.get_session(call_id)
            if not session.call_closed:
                orchestrator.close_call(call_id, reason="pipeline_end")

    @app.post("/api/offer")
    async def offer(
        request: SmallWebRTCRequest,
        background_tasks: BackgroundTasks,
        session_id: str | None = None,
    ) -> dict[str, str]:
        patient_payload = _resolve_patient_payload(request, active_sessions, session_id)

        async def webrtc_connection_callback(connection: SmallWebRTCConnection) -> None:
            background_tasks.add_task(
                _run_voice_session,
                connection,
                patient_payload,
                session_id,
            )

        answer = await webrtc_handler.handle_web_request(
            request=request,
            webrtc_connection_callback=webrtc_connection_callback,
        )
        if answer is None:
            raise HTTPException(status_code=500, detail="No se pudo negociar WebRTC")
        return answer

    @app.patch("/api/offer")
    async def ice_candidate(request: SmallWebRTCPatchRequest) -> dict[str, str]:
        await webrtc_handler.handle_patch_request(request)
        return {"status": "success"}

    @app.get("/sessions/{session_id}/summary")
    async def get_session_summary(session_id: str) -> dict[str, Any]:
        if session_id not in active_sessions:
            raise HTTPException(status_code=404, detail="Sesión no encontrada")

        call_id = session_call_ids.get(session_id)
        if not call_id:
            raise HTTPException(status_code=404, detail="Resumen aún no disponible")

        summary = CallLogService(settings).get_call_summary(call_id)
        if summary is None:
            raise HTTPException(status_code=404, detail="Resumen aún no disponible")
        return summary.model_dump(mode="json")

    @app.api_route(
        "/sessions/{session_id}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def proxy_session(
        session_id: str,
        path: str,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> Any:
        if session_id not in active_sessions:
            raise HTTPException(status_code=404, detail="Sesión no encontrada")

        if not path.endswith("api/offer"):
            raise HTTPException(status_code=404, detail="Ruta no soportada")

        body = await request.json()
        if request.method == "POST":
            webrtc_request = SmallWebRTCRequest(
                sdp=body["sdp"],
                type=body["type"],
                pc_id=body.get("pc_id"),
                restart_pc=body.get("restart_pc"),
                request_data=body.get("request_data")
                or body.get("requestData")
                or active_sessions[session_id],
            )
            return await offer(webrtc_request, background_tasks, session_id=session_id)

        if request.method == "PATCH":
            patch_request = SmallWebRTCPatchRequest(
                pc_id=body["pc_id"],
                candidates=[IceCandidate(**candidate) for candidate in body.get("candidates", [])],
            )
            return await ice_candidate(patch_request)

        raise HTTPException(status_code=405, detail="Método no permitido")

    return app


def _resolve_patient_payload(
    request: SmallWebRTCRequest,
    active_sessions: dict[str, dict[str, Any]],
    session_id: str | None,
) -> dict[str, Any]:
    if session_id and session_id in active_sessions:
        payload = active_sessions[session_id]
        if isinstance(payload, dict):
            return payload

    request_data = request.request_data
    if isinstance(request_data, dict):
        body = request_data.get("body")
        if isinstance(body, dict):
            return body
        return request_data

    raise HTTPException(
        status_code=400,
        detail="Faltan datos del paciente. Inicie sesión desde el formulario.",
    )


def main() -> None:
    load_dotenv(override=True)
    settings = get_settings()
    if not settings.groq_api_key:
        raise ConfigurationError("GROQ_API_KEY es obligatorio")

    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.voice_web_host,
        port=settings.voice_web_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
