"""Pipeline Pipecat WebRTC para el frontend de voz en navegador."""

from __future__ import annotations

import asyncio
from uuid import UUID

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from agent.orchestrator import ConversationOrchestrator
from core.config import Settings, get_settings
from voice.pipeline import VoiceSession, _registration_from_call
from voice.services.kokoro_tts import KokoroTTSService
from voice.services.postop_llm import PostOpLLMService


def build_webrtc_pipeline(
    orchestrator: ConversationOrchestrator,
    call_id: UUID,
    webrtc_connection: SmallWebRTCConnection,
    *,
    settings: Settings | None = None,
) -> VoiceSession:
    """Pipeline voz navegador: WebRTC mic -> Deepgram -> orquestador -> Kokoro -> WebRTC out."""
    settings = settings or get_settings()
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY es obligatorio para llamadas web")

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=settings.voice_sample_rate,
        ),
    )
    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTService.Settings(
            model=settings.deepgram_model,
            language=settings.deepgram_language,
            punctuate=True,
            smart_format=True,
            interim_results=True,
        ),
    )
    llm = PostOpLLMService(
        orchestrator,
        call_id,
        app_settings=settings,
        defer_opening_until_connected=True,
    )
    tts = KokoroTTSService(
        lang_code=settings.kokoro_lang_code,
        voice=settings.kokoro_voice,
        speed=settings.kokoro_speed,
        sample_rate=settings.voice_sample_rate,
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            allow_interruptions=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=settings.voice_pipeline_idle_timeout_secs,
    )
    llm.bind_pipeline_stop(worker.stop_when_done)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _client) -> None:
        asyncio.create_task(llm.ensure_opening())

    return VoiceSession(
        orchestrator=orchestrator,
        registration=_registration_from_call(orchestrator, call_id),
        call_id=call_id,
        llm=llm,
        worker=worker,
        mode="webrtc",
        transport=transport,
    )
