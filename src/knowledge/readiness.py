"""Voice agent readiness checks (indexed corpus + generated protocols)."""

from __future__ import annotations

from dataclasses import dataclass

from core.config import Settings, get_settings
from core.scenarios import canonical_procedure_id, list_scenarios_from_textos
from knowledge.protocol.generator import (
    GENERAL_PROTOCOL_DIR,
    GENERAL_PROTOCOL_FILENAME,
    procedure_protocol_path,
)
from knowledge.store.qdrant_store import QdrantVectorStore


@dataclass(frozen=True)
class VoiceReadiness:
    ready: bool
    detail: str
    indexed_documents: int = 0
    indexed_procedures: tuple[str, ...] = ()
    missing_protocols: tuple[str, ...] = ()


def assess_voice_readiness(
    settings: Settings | None = None,
    *,
    store: QdrantVectorStore | None = None,
) -> VoiceReadiness:
    """Return whether voice calls are allowed (indexed docs + generated protocols)."""
    settings = settings or get_settings()
    resolved_store = store or QdrantVectorStore(settings)

    try:
        sources = resolved_store.list_sources()
    except Exception as exc:  # noqa: BLE001
        return VoiceReadiness(
            ready=False,
            detail=(
                "La base de conocimiento no está disponible. "
                f"Verifique Qdrant e ingesta inicial. ({exc})"
            ),
        )

    if not sources:
        return VoiceReadiness(
            ready=False,
            detail=(
                "No hay documentos indexados. "
                "Ejecute postop-ingest o suba PDFs desde la consola admin."
            ),
            indexed_documents=0,
        )

    protocol_dir = settings.protocol_dir
    general_path = protocol_dir / GENERAL_PROTOCOL_DIR / GENERAL_PROTOCOL_FILENAME
    if not general_path.is_file():
        return VoiceReadiness(
            ready=False,
            detail=(
                "No hay protocolos clínicos generados. "
                "Ejecute postop-ingest para crear protocolos a partir de los PDFs indexados."
            ),
            indexed_documents=len(sources),
        )

    textos_procedures = {
        canonical_procedure_id(procedure_id)
        for procedure_id in list_scenarios_from_textos(settings.textos_dir)
    }
    indexed_procedures = {
        canonical_procedure_id(procedure_id)
        for procedure_id in resolved_store.list_indexed_procedure_ids()
    }
    required = sorted(textos_procedures & indexed_procedures)
    missing = [
        procedure_id
        for procedure_id in required
        if not procedure_protocol_path(protocol_dir, procedure_id).is_file()
    ]

    if missing:
        return VoiceReadiness(
            ready=False,
            detail=(
                "Faltan protocolos clínicos para: "
                f"{', '.join(missing)}. Ejecute postop-ingest o postop-protocols."
            ),
            indexed_documents=len(sources),
            indexed_procedures=tuple(required),
            missing_protocols=tuple(missing),
        )

    return VoiceReadiness(
        ready=True,
        detail="Listo para llamadas de voz.",
        indexed_documents=len(sources),
        indexed_procedures=tuple(required),
    )
