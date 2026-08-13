"""Process-wide embedding model for ingest and RAG (avoid reload per request)."""

from __future__ import annotations

import logging
import time
from threading import Lock

from core.config import Settings, get_settings
from knowledge.ingest.embedder import EmbeddingService

logger = logging.getLogger(__name__)

_embedder: EmbeddingService | None = None
_embedder_lock = Lock()
_warmed_up = False


def get_shared_embedding_service(settings: Settings | None = None) -> EmbeddingService:
    global _embedder
    if _embedder is not None:
        return _embedder
    with _embedder_lock:
        if _embedder is None:
            _embedder = EmbeddingService(settings or get_settings())
            logger.info("Shared EmbeddingService initialized")
    return _embedder


def warmup_embedding_service(settings: Settings | None = None) -> float:
    """Load Granite weights once; returns warmup duration in ms."""
    global _warmed_up
    if _warmed_up:
        return 0.0
    settings = settings or get_settings()
    started = time.perf_counter()
    get_shared_embedding_service(settings).embed_texts(["warmup ingest"])
    elapsed_ms = (time.perf_counter() - started) * 1000
    _warmed_up = True
    logger.info("Embedding warmup finished in %.0f ms", elapsed_ms)
    return elapsed_ms
