"""Construcción del pipeline Pipecat."""

from __future__ import annotations

from dataclasses import dataclass
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
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

from agent.orchestrator import ConversationOrchestrator
from core.config import Settings, get_settings
from scripts.patient_registration import PatientRegistration
from voice.processors.console_input import ConsoleTextInputProcessor
from voice.services.kokoro_tts import KokoroTTSService
from voice.services.postop_llm import PostOpLLMService


@dataclass(frozen=True)
class VoiceSession:
    """Estado de una sesión de voz en Pipecat."""

    orchestrator: ConversationOrchestrator
    registration: PatientRegistration
    call_id: UUID
    llm: PostOpLLMService
    worker: PipelineWorker
    mode: str


def create_orchestrator_and_session(
    registration: PatientRegistration,
    *,
    settings: Settings | None = None,
) -> tuple[ConversationOrchestrator, UUID]:
    settings = settings or get_settings()
    orchestrator = ConversationOrchestrator(settings=settings)
    session = orchestrator.start_call(
        procedure_scenario=registration.procedure_scenario,
        patient_name=registration.patient_name,
        patient_id=registration.patient_id,
        surgery_date=registration.surgery_date,
    )
    return orchestrator, session.call_id


def build_text_pipeline(
    orchestrator: ConversationOrchestrator,
    call_id: UUID,
    *,
    settings: Settings | None = None,
) -> VoiceSession:
    """Pipeline consola: texto -> RAG/Groq -> Kokoro -> altavoz local."""
    settings = settings or get_settings()

    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=False,
            audio_out_enabled=True,
            audio_out_sample_rate=settings.voice_sample_rate,
        )
    )
    llm = PostOpLLMService(orchestrator, call_id, app_settings=settings)
    tts = KokoroTTSService(
        lang_code=settings.kokoro_lang_code,
        voice=settings.kokoro_voice,
        speed=settings.kokoro_speed,
        sample_rate=settings.voice_sample_rate,
    )
    console_input = ConsoleTextInputProcessor(
        opening_ready=llm.opening_ready,
        opening_failed=llm.opening_failed,
        call_ended=llm.call_ended,
    )

    pipeline = Pipeline(
        [
            console_input,
            llm,
            tts,
            transport.output(),
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            allow_interruptions=True,
        ),
        idle_timeout_secs=settings.voice_pipeline_idle_timeout_secs,
    )
    return VoiceSession(
        orchestrator=orchestrator,
        registration=_registration_from_call(orchestrator, call_id),
        call_id=call_id,
        llm=llm,
        worker=worker,
        mode="text",
    )


def build_voice_pipeline(
    orchestrator: ConversationOrchestrator,
    call_id: UUID,
    *,
    settings: Settings | None = None,
) -> VoiceSession:
    """Pipeline voz: micrófono -> Deepgram -> RAG/Groq -> Kokoro -> altavoz."""
    settings = settings or get_settings()
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY es obligatorio en modo voz")

    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=settings.voice_sample_rate,
        )
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
    llm = PostOpLLMService(orchestrator, call_id, app_settings=settings)
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

    return VoiceSession(
        orchestrator=orchestrator,
        registration=_registration_from_call(orchestrator, call_id),
        call_id=call_id,
        llm=llm,
        worker=worker,
        mode="voice",
    )


def _registration_from_call(
    orchestrator: ConversationOrchestrator,
    call_id: UUID,
) -> PatientRegistration:
    session = orchestrator.get_session(call_id)
    return PatientRegistration(
        patient_name=session.patient_name,
        patient_id=session.patient_id or "sin-id",
        surgery_date=session.surgery_date or "",
        procedure_scenario=session.procedure_scenario,
    )
