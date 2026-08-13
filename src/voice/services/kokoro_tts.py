"""Servicio TTS local basado en Kokoro (CPU)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from threading import Lock, Thread

import numpy as np
from kokoro import KPipeline
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TextAggregationMode, TTSService
from pipecat.utils.tracing.service_decorators import traced_tts

from core.config import Settings, get_settings

SENTENCE_SPLIT_PATTERN = r"(?<=[.!?…])\s+"

_pipeline_cache: dict[tuple[str, str], KPipeline] = {}
_pipeline_lock = Lock()


def get_shared_kokoro_pipeline(*, lang_code: str, voice: str) -> KPipeline:
    key = (lang_code, voice)
    cached = _pipeline_cache.get(key)
    if cached is not None:
        return cached
    with _pipeline_lock:
        cached = _pipeline_cache.get(key)
        if cached is None:
            pipeline = KPipeline(lang_code=lang_code, device="cpu", repo_id="hexgrad/Kokoro-82M")
            pipeline.load_single_voice(voice)
            _pipeline_cache[key] = pipeline
            logger.info("Shared Kokoro pipeline loaded | lang={} voice={}", lang_code, voice)
        return _pipeline_cache[key]


def warmup_kokoro_pipeline(settings: Settings | None = None) -> float:
    app_settings = settings or get_settings()
    started = time.perf_counter()
    pipeline = get_shared_kokoro_pipeline(
        lang_code=app_settings.kokoro_lang_code,
        voice=app_settings.kokoro_voice,
    )
    for _graphemes, _phonemes, _audio in pipeline(
        "Hola.",
        voice=app_settings.kokoro_voice,
        speed=app_settings.kokoro_speed,
        split_pattern=SENTENCE_SPLIT_PATTERN,
    ):
        break
    return (time.perf_counter() - started) * 1000


class KokoroTTSService(TTSService):
    """Envuelve ``KPipeline`` de Kokoro para síntesis local en CPU."""

    def __init__(
        self,
        *,
        lang_code: str = "e",
        voice: str = "ef_dora",
        speed: float = 1.0,
        sample_rate: int = 24000,
        **kwargs,
    ) -> None:
        super().__init__(
            sample_rate=sample_rate,
            text_aggregation_mode=TextAggregationMode.SENTENCE,
            push_start_frame=True,
            push_stop_frames=True,
            settings=TTSSettings(
                model="kokoro-82m",
                voice=voice,
                language=lang_code,
            ),
            **kwargs,
        )
        self._lang_code = lang_code
        self._voice = voice
        self._speed = speed
        self._pipeline = get_shared_kokoro_pipeline(lang_code=lang_code, voice=voice)
        logger.info(
            "Kokoro TTS listo | lang={} voice={} sample_rate={}Hz",
            lang_code,
            voice,
            sample_rate,
        )

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        cleaned = text.strip()
        if not cleaned:
            return

        loop = asyncio.get_running_loop()
        chunk_queue: asyncio.Queue[bytes | None | BaseException] = asyncio.Queue()
        started = time.perf_counter()
        first_audio_logged = False

        def producer() -> None:
            try:
                generator = self._pipeline(
                    cleaned,
                    voice=self._voice,
                    speed=self._speed,
                    split_pattern=SENTENCE_SPLIT_PATTERN,
                )
                for _graphemes, _phonemes, audio in generator:
                    pcm = _float_audio_to_pcm16(audio)
                    if pcm:
                        loop.call_soon_threadsafe(chunk_queue.put_nowait, pcm)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(chunk_queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(chunk_queue.put_nowait, None)

        Thread(target=producer, daemon=True).start()

        await self.start_tts_usage_metrics(cleaned)
        while True:
            item = await chunk_queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                logger.exception("Error en síntesis Kokoro")
                yield ErrorFrame(error=f"Kokoro TTS error: {item}")
                return

            if not first_audio_logged:
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "Kokoro TTFB | {:.0f} ms | chars={} | preview={!r}",
                    elapsed_ms,
                    len(cleaned),
                    cleaned[:72],
                )
                first_audio_logged = True

            await self.stop_ttfb_metrics()
            yield TTSAudioRawFrame(item, self.sample_rate, 1, context_id=context_id)


def _float_audio_to_pcm16(audio: np.ndarray) -> bytes:
    """Convierte audio float32/float64 de Kokoro a PCM16 little-endian."""
    array = np.asarray(audio, dtype=np.float32)
    if array.size == 0:
        return b""
    clipped = np.clip(array, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()
