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
    retrieval_top_k: int = 2
    retrieval_score_threshold: float = 0.70

    # LLM agent (Groq — conversación en tiempo real)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_temperature: float = 0.0
    groq_max_output_tokens: int = 2048

    # LLM batch (Gemini — protocolos + validación de ingest)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    gemini_temperature: float = 0.0
    gemini_max_output_tokens: int = 4096
    gemini_json_max_attempts: int = 3
    document_validation_excerpt_chars: int = 3000

    # Protocol generation (RAG + Gemini)
    protocol_retrieval_top_k: int = 12
    protocol_retrieval_per_query_top_k: int = 5
    protocol_retrieval_score_threshold: float = 0.55
    protocol_retrieval_expanded_per_query_top_k: int = 8
    protocol_retrieval_expanded_score_threshold: float = 0.45
    protocol_min_symptoms: int = 3
    protocol_fragment_max_chars: int = 1200
    protocol_max_output_tokens: int = 8192
    protocol_compact_max_chunks: int = 6
    protocol_compact_fragment_max_chars: int = 600
    protocol_compact_max_symptoms: int = 6
    protocol_skip_existing: bool = True
    protocol_generation_delay_seconds: float = 15.0
    protocol_dir: Path = Path("knowledge/protocol")

    # Voz (Pipecat + Deepgram + Kokoro)
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-2"
    deepgram_language: str = "es"
    kokoro_lang_code: str = "e"
    kokoro_voice: str = "ef_dora"
    kokoro_speed: float = 1.0
    voice_sample_rate: int = 24000
    voice_pipeline_idle_timeout_secs: int = 300

    # Agent
    max_turns_per_call: int = 8
    conversation_history_max_turns: int = 3
    rag_context_max_turns: int = 1
    alert_score_threshold: int = 15
    yellow_score_threshold: int = 8
    calls_log_dir: Path = Path("logs/calls")

    # Admin API
    admin_token: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Voice web (Pipecat WebRTC + frontend María)
    voice_web_host: str = "0.0.0.0"
    voice_web_port: int = 7860
    voice_web_cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Dataset
    textos_dir: Path = Path("dataset/textos")

    # OCR (scanned PDF pages — requires Tesseract)
    ocr_enabled: bool = True
    ocr_languages: str = "spa+eng"
    ocr_dpi: int = 200
    ocr_min_chars: int = 80

    @field_validator("calls_log_dir", "textos_dir", "protocol_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def protocol_max_symptoms(self) -> int:
        """Max questions per protocol; aligned with call turn limit."""
        return self.max_turns_per_call


@lru_cache
def get_settings() -> Settings:
    return Settings()
