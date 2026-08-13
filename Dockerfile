# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — Python dependencies (layer cache + uv cache mount)
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

# Lockfile layer — rebuilds only when dependencies change.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --index-strategy unsafe-best-match \
    || uv sync --no-dev --no-install-project --index-strategy unsafe-best-match

COPY src ./src
COPY scripts ./scripts

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --index-strategy unsafe-best-match \
    || uv sync --no-dev --index-strategy unsafe-best-match

# Model warmup layer — Kokoro + IBM Granite (CPU) baked into the image so ingest-init is faster.
# HF downloads use a BuildKit cache mount for speed, then copy into /app/.cache so runtime COPY works.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/tmp/hf-cache \
    bash -c '\
export HF_HOME=/tmp/hf-cache; \
uv run python scripts/download_kokoro_models.py && \
uv run python -c "\
from sentence_transformers import SentenceTransformer; \
from core.config import get_settings; \
SentenceTransformer(get_settings().embedding_model) \
"; \
mkdir -p /app/.cache/huggingface; \
cp -a /tmp/hf-cache/. /app/.cache/huggingface/ \
'

# ---------------------------------------------------------------------------
# Stage 2 — dev dependencies (optional Jupyter profile)
# ---------------------------------------------------------------------------
FROM builder AS builder-dev

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --group dev --index-strategy unsafe-best-match \
    || uv sync --group dev --index-strategy unsafe-best-match

# ---------------------------------------------------------------------------
# Stage 3 — runtime base
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
COPY bootstrap ./bootstrap

# ---------------------------------------------------------------------------
# Stage 4 — production backend
# ---------------------------------------------------------------------------
FROM runtime-base AS runtime

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/.cache /app/.cache
COPY --from=builder /app/.cache/huggingface /app/bootstrap/huggingface

RUN chmod +x /app/scripts/docker-entrypoint.sh /app/scripts/seed_runtime_data.sh

ENV PROTOCOL_DIR=/app/storage/protocols

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD curl -f http://127.0.0.1:${API_PORT:-8000}/openapi.json || exit 1

EXPOSE 8000 7860

# ---------------------------------------------------------------------------
# Stage 5 — Jupyter (profile: analysis)
# ---------------------------------------------------------------------------
FROM runtime-base AS jupyter

COPY --from=builder-dev /app/.venv /app/.venv
COPY --from=builder /app/.cache /app/.cache

RUN mkdir -p /app/notebooks /app/dataset /app/data /app/storage/logs

EXPOSE 8888

CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=", "--NotebookApp.password=", "--notebook-dir=/app/notebooks"]
