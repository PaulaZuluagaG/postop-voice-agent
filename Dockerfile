# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — resolve Python dependencies with uv (production)
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/app/.cache/huggingface \
    KOKORO_LANG_CODE=e \
    KOKORO_VOICE=ef_dora

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    espeak-ng \
    libespeak-ng1 \
    libsndfile1 \
    portaudio19-dev \
    libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts ./scripts

RUN uv sync --frozen --no-dev || uv sync --no-dev

# Precalentar Kokoro TTS y embeddings IBM Granite dentro de la imagen.
RUN uv run python scripts/download_kokoro_models.py
RUN uv run python -c "\
from sentence_transformers import SentenceTransformer; \
from core.config import get_settings; \
SentenceTransformer(get_settings().embedding_model) \
"

# ---------------------------------------------------------------------------
# Stage 2 — resolve dev dependencies (Jupyter / EDA)
# ---------------------------------------------------------------------------
FROM builder AS builder-dev

RUN uv sync --frozen --group dev || uv sync --group dev

# ---------------------------------------------------------------------------
# Stage 3 — runtime base (system libs shared by all Python services)
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/app/.cache/huggingface \
    KOKORO_LANG_CODE=e \
    KOKORO_VOICE=ef_dora

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    espeak-ng \
    libespeak-ng1 \
    libsndfile1 \
    libportaudio2 \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts ./scripts
COPY apps ./apps

# ---------------------------------------------------------------------------
# Stage 4 — production backend (FastAPI admin + Pipecat voice web)
# ---------------------------------------------------------------------------
FROM runtime-base AS runtime

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/.cache /app/.cache

RUN chmod +x /app/scripts/docker-entrypoint.sh

ENV PROTOCOL_DIR=/app/storage/protocols

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -f http://127.0.0.1:${API_PORT:-8000}/openapi.json || exit 1

EXPOSE 8000 7860

# ---------------------------------------------------------------------------
# Stage 5 — Jupyter Lab for exploratory analysis
# ---------------------------------------------------------------------------
FROM runtime-base AS jupyter

COPY --from=builder-dev /app/.venv /app/.venv
COPY --from=builder /app/.cache /app/.cache

RUN mkdir -p /app/notebooks /app/dataset /app/data /app/storage/logs

EXPOSE 8888

CMD [
    "jupyter", "lab",
    "--ip=0.0.0.0",
    "--port=8888",
    "--no-browser",
    "--allow-root",
    "--NotebookApp.token=",
    "--NotebookApp.password=",
    "--notebook-dir=/app/notebooks",
]
