"""Shared heavy voice models — one load per server process."""

from __future__ import annotations

import logging
import time
from threading import Lock

from core.config import Settings, get_settings
from knowledge.retrieval.retriever import ContextualRetriever

logger = logging.getLogger(__name__)

_retriever: ContextualRetriever | None = None
_retriever_lock = Lock()
_warmed_up = False


def get_shared_retriever(settings: Settings | None = None) -> ContextualRetriever:
    """Return a process-wide retriever so embeddings are not reloaded per call."""
    global _retriever
    if _retriever is not None:
        return _retriever
    with _retriever_lock:
        if _retriever is None:
            resolved = settings or get_settings()
            _retriever = ContextualRetriever(resolved)
            logger.info("Shared ContextualRetriever initialized")
    return _retriever


def warmup_voice_runtime(settings: Settings | None = None) -> dict[str, float]:
    """Preload Granite embeddings and Kokoro TTS before the first patient call."""
    global _warmed_up
    if _warmed_up:
        return {}

    settings = settings or get_settings()
    started = time.perf_counter()
    timings: dict[str, float] = {}

    retriever = get_shared_retriever(settings)
    rag_start = time.perf_counter()
    retriever.retrieve(
        "warmup seguimiento postoperatorio",
        procedure_id="appendicitis",
        postop_day=1,
    )
    timings["embedding_warmup_ms"] = (time.perf_counter() - rag_start) * 1000

    from voice.services.kokoro_tts import warmup_kokoro_pipeline

    timings["kokoro_warmup_ms"] = warmup_kokoro_pipeline(settings)
    timings["total_warmup_ms"] = (time.perf_counter() - started) * 1000
    _warmed_up = True
    logger.info("Voice runtime warmup finished: {}", timings)
    return timings
