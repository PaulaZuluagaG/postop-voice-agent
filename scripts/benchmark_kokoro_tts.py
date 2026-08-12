"""Benchmark Kokoro TTS: sentence aggregation vs token-style feeding."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from kokoro import KPipeline

from voice.services.kokoro_tts import SENTENCE_SPLIT_PATTERN, _float_audio_to_pcm16

CLINICAL_SAMPLE = (
    "Hola Paula, soy María, su asistente de seguimiento postoperatorio. "
    "Voy a hacerle unas preguntas para revisar cómo va su recuperación. "
    "¿Cuál es su temperatura corporal actual?"
)


@dataclass(frozen=True)
class BenchmarkResult:
    mode: str
    ttfb_ms: float
    total_ms: float
    audio_chunks: int


def _split_sentences(text: str) -> list[str]:
    parts = [
        part.strip() for part in re.split(SENTENCE_SPLIT_PATTERN, text.strip()) if part.strip()
    ]
    return parts or [text.strip()]


def _first_chunk_ttfb(
    pipeline: KPipeline, text: str, *, voice: str, speed: float
) -> tuple[float, float, int]:
    started = time.perf_counter()
    first_at: float | None = None
    chunks = 0
    generator = pipeline(
        text,
        voice=voice,
        speed=speed,
        split_pattern=SENTENCE_SPLIT_PATTERN,
    )
    for _graphemes, _phonemes, audio in generator:
        pcm = _float_audio_to_pcm16(audio)
        if not pcm:
            continue
        chunks += 1
        if first_at is None:
            first_at = time.perf_counter()
    finished = time.perf_counter()
    ttfb_ms = ((first_at or finished) - started) * 1000
    total_ms = (finished - started) * 1000
    return ttfb_ms, total_ms, chunks


def _token_style_feed(
    pipeline: KPipeline, text: str, *, voice: str, speed: float
) -> tuple[float, float, int]:
    """Simulate feeding Kokoro on each token boundary (worst case for prosody)."""
    started = time.perf_counter()
    first_at: float | None = None
    chunks = 0
    buffer = ""
    for token in text.split():
        buffer = f"{buffer} {token}".strip() if buffer else token
        if not re.search(r"[.!?…]$", buffer):
            continue
        ttfb_ms, _total_ms, part_chunks = _first_chunk_ttfb(
            pipeline, buffer, voice=voice, speed=speed
        )
        chunks += part_chunks
        if first_at is None:
            first_at = started + (ttfb_ms / 1000)
        buffer = ""
    if buffer.strip():
        ttfb_ms, _total_ms, part_chunks = _first_chunk_ttfb(
            pipeline, buffer, voice=voice, speed=speed
        )
        chunks += part_chunks
        if first_at is None:
            first_at = started + (ttfb_ms / 1000)
    finished = time.perf_counter()
    return ((first_at or finished) - started) * 1000, (finished - started) * 1000, chunks


def _sentence_style_feed(
    pipeline: KPipeline, text: str, *, voice: str, speed: float
) -> tuple[float, float, int]:
    started = time.perf_counter()
    first_at: float | None = None
    chunks = 0
    for sentence in _split_sentences(text):
        ttfb_ms, _total_ms, part_chunks = _first_chunk_ttfb(
            pipeline, sentence, voice=voice, speed=speed
        )
        chunks += part_chunks
        if first_at is None:
            first_at = started + (ttfb_ms / 1000)
    finished = time.perf_counter()
    return ((first_at or finished) - started) * 1000, (finished - started) * 1000, chunks


def run_benchmark(
    *,
    lang_code: str = "e",
    voice: str = "ef_dora",
    speed: float = 1.0,
    text: str = CLINICAL_SAMPLE,
) -> list[BenchmarkResult]:
    pipeline = KPipeline(lang_code=lang_code, device="cpu", repo_id="hexgrad/Kokoro-82M")
    pipeline.load_single_voice(voice)

    results: list[BenchmarkResult] = []

    ttfb, total, chunks = _first_chunk_ttfb(pipeline, text, voice=voice, speed=speed)
    results.append(BenchmarkResult("full_text (una sola llamada Kokoro)", ttfb, total, chunks))

    ttfb, total, chunks = _sentence_style_feed(pipeline, text, voice=voice, speed=speed)
    results.append(BenchmarkResult("sentence (como Pipecat SENTENCE)", ttfb, total, chunks))

    ttfb, total, chunks = _token_style_feed(pipeline, text, voice=voice, speed=speed)
    results.append(BenchmarkResult("token (fragmentos por puntuación)", ttfb, total, chunks))

    return results


def main() -> None:
    print("Benchmark Kokoro TTS (CPU)\n")
    print(f"Texto ({len(CLINICAL_SAMPLE)} chars):\n  {CLINICAL_SAMPLE}\n")
    for result in run_benchmark():
        print(
            f"- {result.mode}\n"
            f"  TTFB: {result.ttfb_ms:.0f} ms | total: {result.total_ms:.0f} ms | "
            f"chunks: {result.audio_chunks}"
        )


if __name__ == "__main__":
    main()
