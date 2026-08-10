"""Generate and persist post-operative protocols from indexed knowledge."""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from core.config import Settings, get_settings
from core.exceptions import LLMError
from core.models import ProcedureScenario, RetrievedChunk
from core.retry import gemini_is_daily_quota_error
from core.scenarios import list_scenarios_from_textos
from knowledge.protocol.fallback import merge_with_general_fallback
from knowledge.protocol.gemini_client import ProtocolGeminiClient
from knowledge.protocol.models import (
    PostOpProtocol,
    ProcedureProtocolResult,
    ProtocolGenerationReport,
    ProtocolThresholds,
)
from knowledge.protocol.retrieval import retrieve_protocol_context
from knowledge.retrieval.retriever import ContextualRetriever
from knowledge.store.qdrant_store import QdrantVectorStore

logger = logging.getLogger(__name__)

GENERAL_PROTOCOL_DIR = "general"
GENERAL_PROTOCOL_FILENAME = "protocol.json"
BUNDLED_GENERAL_PROTOCOL = "general_protocol.json"


def _bundled_general_protocol_path() -> Path:
    return Path(__file__).resolve().parent / BUNDLED_GENERAL_PROTOCOL


def write_general_protocol(output_dir: Path) -> Path:
    """Copy the bundled generic protocol to knowledge/protocol/general/."""
    destination_dir = output_dir / GENERAL_PROTOCOL_DIR
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / GENERAL_PROTOCOL_FILENAME
    shutil.copyfile(_bundled_general_protocol_path(), destination)
    return destination


def procedure_protocol_path(
    output_dir: Path,
    procedure_scenario: ProcedureScenario,
) -> Path:
    return output_dir / procedure_scenario.value / GENERAL_PROTOCOL_FILENAME


def write_procedure_protocol(
    output_dir: Path,
    procedure_scenario: ProcedureScenario,
    protocol: PostOpProtocol,
) -> Path:
    destination_dir = output_dir / procedure_scenario.value
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / GENERAL_PROTOCOL_FILENAME
    destination.write_text(
        json.dumps(protocol.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination


def _is_truncation_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "truncated" in message or "max_tokens" in message


def _chunk_source_ids(chunks: list[RetrievedChunk]) -> list[str]:
    return sorted({chunk.source_id for chunk in chunks if chunk.source_id})


def _empty_protocol_payload(procedure: str) -> dict:
    return {
        "procedure": procedure,
        "symptoms": [],
        "thresholds": ProtocolThresholds(verde=0, amarillo=8, rojo=15).model_dump(),
        "alert_signs": [],
    }


def _generate_protocol_with_llm(
    *,
    resolved_llm: ProtocolGeminiClient,
    procedure: str,
    chunks: list[RetrievedChunk],
    resolved_settings: Settings,
) -> PostOpProtocol:
    """Call Gemini for protocol JSON, with compact retry on output truncation."""
    try:
        return resolved_llm.generate_protocol_json(procedure, chunks)
    except LLMError as exc:
        if not _is_truncation_error(exc):
            raise
        compact_chunks = chunks[: resolved_settings.protocol_compact_max_chunks]
        if not compact_chunks:
            raise
        logger.warning(
            "Output truncated for %s; retrying with %s compact chunks",
            procedure,
            len(compact_chunks),
        )
        return resolved_llm.generate_protocol_json(
            procedure,
            compact_chunks,
            compact=True,
        )


def _generate_protocol_for_procedure(
    *,
    procedure_scenario: ProcedureScenario,
    resolved_settings: Settings,
    resolved_retriever: ContextualRetriever,
    resolved_llm: ProtocolGeminiClient,
) -> tuple[PostOpProtocol, list[RetrievedChunk], bool]:
    """Generate a protocol with retry on sparse output and general-protocol fallback."""
    min_symptoms = resolved_settings.protocol_min_symptoms
    used_fallback = False

    _rag_query, chunks, _elapsed_ms = retrieve_protocol_context(
        resolved_retriever,
        procedure_scenario,
        settings=resolved_settings,
    )
    if not chunks:
        raise ValueError(
            f"{procedure_scenario.value}: no RAG fragments retrieved for protocol generation"
        )

    try:
        protocol = _generate_protocol_with_llm(
            resolved_llm=resolved_llm,
            procedure=procedure_scenario.value,
            chunks=chunks,
            resolved_settings=resolved_settings,
        )
    except LLMError as exc:
        logger.warning(
            "LLM protocol generation failed for %s; applying general fallback: %s",
            procedure_scenario.value,
            exc,
        )
        protocol = merge_with_general_fallback(
            PostOpProtocol.from_llm_output(
                _empty_protocol_payload(procedure_scenario.value),
                source_ids=_chunk_source_ids(chunks),
            ),
            procedure_scenario.value,
            min_symptoms=min_symptoms,
            max_symptoms=resolved_settings.protocol_max_symptoms,
        )
        used_fallback = True
        return protocol, chunks, used_fallback

    if len(protocol.symptoms) < min_symptoms:
        logger.info(
            "Sparse protocol for %s (%s symptoms); retrying with expanded retrieval",
            procedure_scenario.value,
            len(protocol.symptoms),
        )
        _expanded_query, expanded_chunks, _expanded_elapsed_ms = retrieve_protocol_context(
            resolved_retriever,
            procedure_scenario,
            settings=resolved_settings,
            expanded=True,
        )
        if expanded_chunks:
            try:
                retry_protocol = _generate_protocol_with_llm(
                    resolved_llm=resolved_llm,
                    procedure=procedure_scenario.value,
                    chunks=expanded_chunks,
                    resolved_settings=resolved_settings,
                )
            except LLMError as exc:
                logger.warning(
                    "Expanded retrieval LLM failed for %s: %s",
                    procedure_scenario.value,
                    exc,
                )
                retry_protocol = protocol
            else:
                if len(retry_protocol.symptoms) > len(protocol.symptoms):
                    protocol = retry_protocol
                    chunks = expanded_chunks

    if len(protocol.symptoms) < min_symptoms:
        logger.warning(
            "Applying general-protocol fallback for %s (%s symptoms after retry)",
            procedure_scenario.value,
            len(protocol.symptoms),
        )
        protocol = merge_with_general_fallback(
            protocol,
            procedure_scenario.value,
            min_symptoms=min_symptoms,
            max_symptoms=resolved_settings.protocol_max_symptoms,
        )
        used_fallback = True

    if len(protocol.symptoms) == 0:
        raise ValueError(f"{procedure_scenario.value}: protocol has no symptoms after fallback")

    return protocol, chunks, used_fallback


def generate_protocols_for_indexed_procedures(
    *,
    settings: Settings | None = None,
    store: QdrantVectorStore | None = None,
    retriever: ContextualRetriever | None = None,
    llm: ProtocolGeminiClient | None = None,
    output_dir: Path | None = None,
    force: bool = False,
) -> ProtocolGenerationReport:
    """Generate procedure-specific protocols for all indexed scenarios in Qdrant."""
    resolved_settings = settings or get_settings()
    resolved_store = store or QdrantVectorStore(resolved_settings)
    resolved_retriever = retriever or ContextualRetriever(resolved_settings, store=resolved_store)
    resolved_llm = llm or ProtocolGeminiClient(resolved_settings)
    resolved_output_dir = output_dir or resolved_settings.protocol_dir
    skip_existing = resolved_settings.protocol_skip_existing and not force

    report = ProtocolGenerationReport(
        general_protocol_path=str(write_general_protocol(resolved_output_dir)),
    )

    textos_scenarios = set(list_scenarios_from_textos(resolved_settings.textos_dir))
    indexed_scenarios = set(resolved_store.list_indexed_scenarios())
    scenarios_to_process = sorted(
        textos_scenarios & indexed_scenarios,
        key=lambda scenario: scenario.value,
    )

    pending_llm_call = False
    for procedure_scenario in scenarios_to_process:
        existing_path = procedure_protocol_path(resolved_output_dir, procedure_scenario)
        if skip_existing and existing_path.exists():
            report.skipped_procedures.append(procedure_scenario.value)
            logger.info("Skipping existing protocol for %s", procedure_scenario.value)
            continue

        delay_seconds = resolved_settings.protocol_generation_delay_seconds
        if pending_llm_call and delay_seconds > 0:
            logger.info(
                "Waiting %.1fs before next Gemini protocol call (RPM pacing)",
                delay_seconds,
            )
            time.sleep(delay_seconds)

        try:
            protocol, chunks, used_fallback = _generate_protocol_for_procedure(
                procedure_scenario=procedure_scenario,
                resolved_settings=resolved_settings,
                resolved_retriever=resolved_retriever,
                resolved_llm=resolved_llm,
            )
            if used_fallback:
                logger.info(
                    "Protocol for %s supplemented from general template",
                    procedure_scenario.value,
                )

            pending_llm_call = True
            protocol_path = write_procedure_protocol(
                resolved_output_dir,
                procedure_scenario,
                protocol,
            )
            updated_points = resolved_store.set_protocol_payload(
                procedure_scenario,
                protocol.model_dump(mode="json"),
            )
            report.procedures.append(
                ProcedureProtocolResult(
                    procedure_scenario=procedure_scenario.value,
                    protocol_path=str(protocol_path),
                    chunks_retrieved=len(chunks),
                    qdrant_points_updated=updated_points,
                )
            )
            logger.info(
                "Generated protocol for %s (%s chunks, %s Qdrant points)",
                procedure_scenario.value,
                len(chunks),
                updated_points,
            )
        except Exception as exc:  # noqa: BLE001
            message = f"{procedure_scenario.value}: {exc}"
            report.errors.append(message)
            logger.exception("Failed to generate protocol for %s", procedure_scenario.value)
            if _is_daily_gemini_quota_error(exc):
                report.errors.append("Gemini daily quota exhausted; stopping remaining procedures.")
                break

    return report


def _is_daily_gemini_quota_error(exc: Exception) -> bool:
    if gemini_is_daily_quota_error(exc):
        return True
    if isinstance(exc, LLMError) and exc.__cause__ is not None:
        return gemini_is_daily_quota_error(exc.__cause__)
    return False
