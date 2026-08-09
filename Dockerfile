# syntax=docker/dockerfile:1

FROM astral-sh/uv:python3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/app/.cache/huggingface \
    KOKORO_LANG_CODE=e \
    KOKORO_VOICE=ef_dora

WORKDIR /app

# Dependencias de sistema: audio, Kokoro (espeak-ng), PyAudio/portaudio.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    espeak-ng \
    libespeak-ng1 \
    libsndfile1 \
    portaudio19-dev \
    libportaudio2 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* README.md ./
COPY core ./core
COPY agent ./agent
COPY knowledge ./knowledge
COPY api ./api
COPY voice ./voice
COPY scripts ./scripts

RUN uv sync --frozen --no-dev || uv sync --no-dev

# Precalentar modelo Kokoro y voz española dentro de la imagen.
RUN uv run python scripts/download_kokoro_models.py

EXPOSE 8765

CMD ["uv", "run", "postop-voice", "--mode", "text"]
