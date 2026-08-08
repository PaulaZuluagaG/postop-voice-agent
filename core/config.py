"""Single source of truth for environment configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "postop_clinical_knowledge"
    qdrant_timeout_seconds: float = 30.0

    # Embeddings
    embedding_model: str = "ibm-granite/granite-embedding-97m-multilingual-r2"
    embedding_batch_size: int = 32
    embedding_dimension: int = 384

    # Chunking
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    min_document_chars: int = 200

    # Retrieval
    retrieval_top_k: int = 5
    retrieval_score_threshold: float = 0.35

    # LLM (Ollama)
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "phi3.5"
    ollama_temperature: float = 0.1
    ollama_max_output_tokens: int = 512

    # Agent
    max_turns_per_call: int = 10
    alert_score_threshold: int = 15
    yellow_score_threshold: int = 8
    calls_log_dir: Path = Path("logs/calls")

    # Dataset
    textos_dir: Path = Path("dataset/textos")

    @field_validator("calls_log_dir", "textos_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
