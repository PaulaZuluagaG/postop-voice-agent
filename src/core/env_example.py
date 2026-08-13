"""Generate .env templates from Settings (single source of truth in config.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_core import PydanticUndefined

from core.config import Settings
from core.paths import project_root

SECRET_FIELDS = frozenset(
    {
        "groq_api_key",
        "gemini_api_key",
        "deepgram_api_key",
        "admin_token",
    }
)

SECRET_PLACEHOLDERS = {
    "groq_api_key": "your_groq_api_key_here",
    "gemini_api_key": "your_gemini_api_key_here",
    "deepgram_api_key": "your_deepgram_api_key_here",
    "admin_token": "change_me_admin_token",
}

ENV_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Qdrant (vector store)", ("qdrant_",)),
    ("Embeddings (sentence-transformers / Hugging Face)", ("embedding_",)),
    ("Chunking (ingest)", ("chunk_", "min_document_chars")),
    ("Retrieval (RAG)", ("retrieval_",)),
    ("LLM agent (Groq — conversación en tiempo real)", ("groq_",)),
    ("LLM batch (Gemini — protocolos + validación de ingest)", ("gemini_", "document_validation_")),
    ("Protocol generation (RAG + Gemini)", ("protocol_",)),
    ("Voz (Pipecat + Deepgram STT + Kokoro TTS)", ("deepgram_", "kokoro_", "voice_")),
    (
        "Agent (orchestrator / scoring)",
        (
            "max_turns_",
            "risk_factor_",
            "conversation_",
            "rag_context_",
            "alert_",
            "yellow_",
            "calls_log_",
        ),
    ),
    ("Admin API", ("admin_", "api_")),
    ("Voice web (Pipecat WebRTC)", ("voice_web_",)),
    ("Dataset (PDFs clínicos)", ("textos_",)),
    ("OCR (PDFs escaneados)", ("ocr_",)),
)

DOCKER_COMPOSE_VARS: tuple[tuple[str, str, str], ...] = (
    (
        "NEXT_PUBLIC_VOICE_API_URL",
        "http://localhost:7860",
        "URL de voz accesible desde el navegador (build del frontend paciente)",
    ),
    ("FRONTEND_PACIENTE_PORT", "3000", "Puerto host del frontend paciente"),
    ("FRONTEND_ADMIN_PORT", "8080", "Puerto host del frontend admin"),
    ("JUPYTER_PORT", "8888", "Puerto host de Jupyter (--profile analysis)"),
)

HEADER = """\
# Plantilla de variables de entorno — PostOp Voice Agent
#
# Uso habitual:
#   cp .env.example .env
#   # Edita .env: rellena las API keys y ajusta lo que necesites
#
# Los defaults viven en src/core/config.py (Settings). Este archivo se genera
# desde ahí para que no se desincronice:
#   uv run postop-config-example              # regenera .env.example (completo)
#   uv run postop-config-example --minimal    # solo secretos + Docker
#   uv run postop-config-example --show       # configuración efectiva (.env cargado)
"""


def env_var_name(field_name: str) -> str:
    return field_name.upper()


def field_default(field_name: str) -> Any:
    field = Settings.model_fields[field_name]
    if field.default is not PydanticUndefined:
        return field.default
    if field.default_factory is not None:
        return field.default_factory()
    raise KeyError(f"No default for field: {field_name}")


def format_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        try:
            return str(value.relative_to(project_root()))
        except ValueError:
            return str(value)
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _section_for_field(field_name: str) -> str | None:
    for title, prefixes in ENV_SECTIONS:
        if any(field_name.startswith(prefix) for prefix in prefixes):
            return title
    return None


def generate_minimal_env_example() -> str:
    lines = [HEADER, "# === Obligatorio: secretos ===", ""]
    for field_name in Settings.model_fields:
        if field_name not in SECRET_FIELDS:
            continue
        env_name = env_var_name(field_name)
        placeholder = SECRET_PLACEHOLDERS[field_name]
        lines.append(f"{env_name}={placeholder}")
    lines.extend(
        [
            "",
            "# === Docker Compose (despliegue local) ===",
            "# QDRANT_HOST y rutas de datos los fija docker-compose.yml en contenedores.",
            "",
        ]
    )
    for env_name, default, description in DOCKER_COMPOSE_VARS:
        lines.append(f"# {description}")
        lines.append(f"{env_name}={default}")
        lines.append("")
    lines.append(
        "# Overrides opcionales (descomenta solo si necesitas cambiar el default de config.py):"
    )
    lines.append("# GEMINI_MODEL=gemini-3.5-flash-lite")
    lines.append("# GROQ_TEMPERATURE=0.1")
    lines.append("")
    return "\n".join(lines)


def generate_full_env_example() -> str:
    lines = [
        HEADER,
        "# Referencia completa: cada línea refleja el default actual de Settings.",
        "",
    ]
    seen_sections: set[str | None] = set()
    for field_name in Settings.model_fields:
        section = _section_for_field(field_name)
        if section not in seen_sections:
            if section:
                lines.extend(["", f"# {section}", ""])
            seen_sections.add(section)
        env_name = env_var_name(field_name)
        default = format_env_value(field_default(field_name))
        if field_name in SECRET_FIELDS:
            lines.append(f"{env_name}={SECRET_PLACEHOLDERS[field_name]}")
        else:
            lines.append(f"{env_name}={default}")
    lines.extend(
        [
            "",
            "# === Docker Compose (variables de despliegue, no están en Settings) ===",
            "# En contenedores, docker-compose.yml suele sobreescribir QDRANT_HOST y rutas.",
            "",
        ]
    )
    for env_name, default, description in DOCKER_COMPOSE_VARS:
        lines.append(f"# {description}")
        lines.append(f"{env_name}={default}")
    lines.append("")
    return "\n".join(lines)


def format_effective_settings(settings: Settings) -> str:
    lines = ["# Configuración efectiva (Settings + .env)", ""]
    for field_name in Settings.model_fields:
        value = getattr(settings, field_name)
        env_name = env_var_name(field_name)
        if field_name in SECRET_FIELDS:
            display = "***" if value else "(vacío)"
        else:
            display = format_env_value(value)
        lines.append(f"{env_name}={display}")
    lines.append("")
    return "\n".join(lines)


def write_env_example(path: Path, *, minimal: bool = False) -> None:
    content = generate_minimal_env_example() if minimal else generate_full_env_example()
    path.write_text(content, encoding="utf-8")
