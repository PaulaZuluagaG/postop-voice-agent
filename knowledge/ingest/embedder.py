"""Embedding generation using Granite multilingual model."""

from __future__ import annotations

from core.config import Settings, get_settings
from core.exceptions import EmbeddingError
from core.models import TextChunk


class EmbeddingService:
    """Lazy-loaded sentence-transformers wrapper."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._settings.embedding_model)
        return self._model

    @property
    def dimension(self) -> int:
        return self._settings.embedding_dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            model = self._load_model()
            vectors = model.encode(
                texts,
                batch_size=self._settings.embedding_batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return [vector.tolist() for vector in vectors]
        except Exception as exc:  # noqa: BLE001 - surface as domain error
            raise EmbeddingError(f"Failed to embed {len(texts)} texts") from exc

    def embed_chunks(self, chunks: list[TextChunk]) -> list[list[float]]:
        return self.embed_texts([chunk.text for chunk in chunks])
