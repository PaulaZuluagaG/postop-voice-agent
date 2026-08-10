"""Tests for protocol generation pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from groq import RateLimitError

from core.exceptions import LLMError
from core.models import DocumentType, ProcedureScenario, RetrievedChunk
from core.retry import groq_is_daily_quota_error, with_groq_retry
from knowledge.protocol.fallback import load_bundled_general_protocol, merge_with_general_fallback
from knowledge.protocol.gemini_client import ProtocolGeminiClient
from knowledge.protocol.generator import (
    _generate_protocol_for_procedure,
    _generate_protocol_with_llm,
    _is_truncation_error,
    generate_protocols_for_indexed_procedures,
    procedure_protocol_path,
    write_general_protocol,
)
from knowledge.protocol.models import (
    PostOpProtocol,
    ProtocolThresholds,
    SymptomDefinition,
    SymptomLevel,
)
from knowledge.protocol.prompts import (
    build_protocol_system_prompt,
    build_protocol_user_prompt,
    format_protocol_fragments,
    truncate_fragment_text,
)
from knowledge.protocol.retrieval import (
    merge_retrieved_chunks,
    protocol_queries_for,
    retrieve_protocol_context,
)
from knowledge.retrieval.retriever import ContextualRetriever
from knowledge.store.qdrant_store import QdrantVectorStore


def _complete_protocol(procedure: str = "appendicitis") -> PostOpProtocol:
    level = SymptomLevel(min=0, max=3, points=0, label="verde")
    return PostOpProtocol(
        procedure=procedure,
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[
            SymptomDefinition(
                id="dolor",
                question="Del 0 al 10, ¿cómo califica su dolor?",
                type="numeric",
                levels=[level],
                fuentes=["doc_apendicitis_01"],
            ),
            SymptomDefinition(
                id="fiebre",
                question="¿Ha tenido fiebre?",
                type="numeric",
                levels=[level],
                fuentes=["doc_apendicitis_01"],
            ),
            SymptomDefinition(
                id="nauseas",
                question="¿Ha tenido náuseas?",
                type="numeric",
                levels=[level],
                fuentes=["doc_apendicitis_01"],
            ),
        ],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=["dolor intenso (≥8/10)"],
        source_ids=["doc_apendicitis_01"],
    )


def _sample_protocol_payload() -> dict:
    return {
        "procedure": "apendicectomía",
        "symptoms": [
            {
                "id": "dolor",
                "question": "Del 0 al 10, ¿cómo califica su dolor abdominal?",
                "type": "numeric",
                "levels": [
                    {"min": 0, "max": 3, "points": 0, "label": "verde"},
                    {"min": 4, "max": 7, "points": 4, "label": "amarillo"},
                    {"min": 8, "max": 10, "points": 10, "label": "rojo"},
                ],
                "fuentes": ["doc_apendicitis_01"],
            }
        ],
        "thresholds": {"verde": 0, "amarillo": 8, "rojo": 15},
        "alert_signs": ["dolor intenso (≥8/10)"],
    }


def _sample_chunk(source_id: str = "doc_apendicitis_01") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-1",
        source_id=source_id,
        text="Dolor abdominal en escala 0-10. Fiebre >38.5°C es signo de alarma.",
        token_count=20,
        chunk_index=0,
        page_start=1,
        page_end=1,
        procedure_scenario=ProcedureScenario.APPENDICITIS,
        document_type=DocumentType.GUIDE,
        language="es",
        file_name="appendicitis.pdf",
        score=0.91,
    )


def test_postop_protocol_validates_example_json() -> None:
    protocol = PostOpProtocol.from_llm_output(
        _sample_protocol_payload(),
        source_ids=["doc_apendicitis_01", "doc_apendicitis_02"],
    )
    assert protocol.procedure == "apendicectomía"
    assert protocol.version == "1.0"
    assert protocol.source_ids == ["doc_apendicitis_01", "doc_apendicitis_02"]
    assert protocol.symptoms[0].type == "numeric"
    assert protocol.thresholds.rojo == 15


def test_truncate_fragment_text() -> None:
    assert truncate_fragment_text("abc", 10) == "abc"
    assert truncate_fragment_text("abcdefghij", 7) == "abcd..."


def test_format_protocol_fragments_truncates_and_deduplicates() -> None:
    long_text = "x" * 1000
    formatted = format_protocol_fragments(
        [
            (1, "doc_a", "a.pdf", long_text),
            (2, "doc_b", "b.pdf", long_text),
        ],
        max_chars=700,
    )
    assert formatted.count("xxx") > 0
    assert formatted.count("--- Fragmento") == 1


def test_format_protocol_fragments_includes_source_ids() -> None:
    formatted = format_protocol_fragments(
        [(1, "doc_apendicitis_01", "appendicitis.pdf", "Dolor abdominal")]
    )
    assert "Fragmento 1" in formatted
    assert "source_id: doc_apendicitis_01" in formatted
    assert "Dolor abdominal" in formatted


def test_retrieve_protocol_context_uses_multi_query_and_configured_threshold() -> None:
    retriever = MagicMock(spec=ContextualRetriever)
    chunk_a = _sample_chunk("doc_a")
    chunk_b = _sample_chunk("doc_b")
    chunk_b.chunk_id = "chunk-2"
    retriever.retrieve.side_effect = [
        ("query", [chunk_a], 5.0),
        ("query", [chunk_b], 5.0),
        ("query", [], 5.0),
        ("query", [], 5.0),
    ]
    settings = MagicMock()
    settings.protocol_retrieval_top_k = 12
    settings.protocol_retrieval_per_query_top_k = 5
    settings.protocol_retrieval_score_threshold = 0.55

    _query, chunks, _elapsed_ms = retrieve_protocol_context(
        retriever,
        ProcedureScenario.APPENDICITIS,
        settings=settings,
    )

    assert retriever.retrieve.call_count == len(
        protocol_queries_for(ProcedureScenario.APPENDICITIS)
    )
    assert len(chunks) == 2
    _, kwargs = retriever.retrieve.call_args_list[0]
    assert kwargs["top_k"] == 5
    assert kwargs["score_threshold"] == 0.55
    assert kwargs["procedure_scenario"] == ProcedureScenario.APPENDICITIS


def test_merge_retrieved_chunks_deduplicates_by_chunk_id() -> None:
    chunk_a = _sample_chunk("doc_a")
    chunk_b = _sample_chunk("doc_b")
    chunk_b.chunk_id = "chunk-2"
    chunk_a_high = chunk_a.model_copy(update={"score": 0.95})
    chunk_a_low = chunk_a.model_copy(update={"score": 0.60})

    merged = merge_retrieved_chunks(
        [[chunk_a_low], [chunk_a_high, chunk_b]],
        max_chunks=12,
    )

    assert len(merged) == 2
    assert merged[0].chunk_id == "chunk-1"
    assert merged[0].score == 0.95


def test_merge_with_general_fallback_supplements_sparse_protocol() -> None:
    sparse = PostOpProtocol(
        procedure="cervical_cancer",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=["sangrado abundante"],
        source_ids=["doc_a"],
    )

    merged = merge_with_general_fallback(sparse, "cervical_cancer", min_symptoms=3)

    assert merged.procedure == "cervical_cancer"
    assert len(merged.symptoms) >= 3
    assert "sangrado abundante" in merged.alert_signs
    assert any(sign in merged.alert_signs for sign in load_bundled_general_protocol().alert_signs)


def test_load_bundled_general_protocol_has_symptoms() -> None:
    general = load_bundled_general_protocol()
    assert general.procedure == "desconocido"
    assert len(general.symptoms) >= 3


def test_write_general_protocol_creates_file(tmp_path: Path) -> None:
    destination = write_general_protocol(tmp_path)
    assert destination.exists()
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["procedure"] == "desconocido"
    assert len(payload["symptoms"]) >= 1


def test_protocol_gemini_client_parses_json_response() -> None:
    settings = MagicMock()
    settings.gemini_api_key = "test-key"
    settings.gemini_temperature = 0.0
    settings.protocol_max_output_tokens = 8192
    settings.protocol_fragment_max_chars = 1200
    settings.protocol_compact_fragment_max_chars = 600
    settings.protocol_compact_max_symptoms = 6
    settings.max_turns_per_call = 8
    settings.protocol_max_symptoms = 8

    client = ProtocolGeminiClient(settings)

    with patch.object(
        client._gemini,
        "generate_json",
        return_value=_sample_protocol_payload(),
    ) as generate_json:
        protocol = client.generate_protocol_json("appendicitis", [_sample_chunk()])

    assert protocol.procedure == "apendicectomía"
    assert protocol.symptoms[0].fuentes == ["doc_apendicitis_01"]
    generate_json.assert_called_once()
    kwargs = generate_json.call_args.kwargs
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_output_tokens"] == 8192


def test_protocol_gemini_client_compact_mode_uses_shorter_fragments() -> None:
    settings = MagicMock()
    settings.gemini_api_key = "test-key"
    settings.gemini_temperature = 0.0
    settings.protocol_max_output_tokens = 8192
    settings.protocol_fragment_max_chars = 1200
    settings.protocol_compact_fragment_max_chars = 600
    settings.protocol_compact_max_symptoms = 6
    settings.max_turns_per_call = 8
    settings.protocol_max_symptoms = 8

    client = ProtocolGeminiClient(settings)

    with patch.object(
        client._gemini,
        "generate_json",
        return_value=_sample_protocol_payload(),
    ) as generate_json:
        client.generate_protocol_json("appendicitis", [_sample_chunk()], compact=True)

    user_prompt = generate_json.call_args.kwargs["user_prompt"]
    assert "Modo compacto" in user_prompt


def test_build_protocol_system_prompt_uses_max_symptoms() -> None:
    prompt = build_protocol_system_prompt(max_symptoms=8)
    assert "Máximo 8 síntomas" in prompt
    assert "entre 3 y 8 síntomas" in prompt


def test_build_protocol_user_prompt_compact_suffix() -> None:
    prompt = build_protocol_user_prompt(
        procedure="colorectal_cancer",
        text="fragmento",
        max_symptoms=8,
        compact=True,
        compact_max_symptoms=6,
    )
    assert "Entre 1 y 8 síntomas" in prompt
    assert "máximo 6 síntomas" in prompt


def test_protocol_max_symptoms_matches_max_turns() -> None:
    from core.config import Settings

    settings = Settings(max_turns_per_call=8)
    assert settings.protocol_max_symptoms == 8


def test_is_truncation_error() -> None:
    assert _is_truncation_error(LLMError("output truncated (MAX_TOKENS)")) is True
    assert _is_truncation_error(LLMError("network failure")) is False


def test_generate_protocol_with_llm_retries_compact_on_truncation() -> None:
    settings = MagicMock()
    settings.protocol_compact_max_chunks = 6

    llm = MagicMock()
    llm.generate_protocol_json.side_effect = [
        LLMError("Gemini protocol generation failed: output truncated (MAX_TOKENS)"),
        _complete_protocol("colorectal_cancer"),
    ]

    protocol = _generate_protocol_with_llm(
        resolved_llm=llm,
        procedure="colorectal_cancer",
        chunks=[_sample_chunk()],
        resolved_settings=settings,
    )

    assert protocol.procedure == "colorectal_cancer"
    assert llm.generate_protocol_json.call_count == 2
    assert llm.generate_protocol_json.call_args_list[1].kwargs["compact"] is True


def test_protocol_gemini_client_requires_api_key() -> None:
    settings = MagicMock()
    settings.gemini_api_key = ""
    with patch("knowledge.protocol.gemini_client.GeminiClient", side_effect=LLMError("missing")):
        with pytest.raises(LLMError):
            ProtocolGeminiClient(settings)


def test_groq_daily_quota_is_not_retried() -> None:
    exc = RateLimitError(
        "rate limit",
        response=MagicMock(headers={}),
        body={"error": {"message": "tokens per day (TPD): Limit 100000"}},
    )

    def _fail() -> None:
        raise exc

    assert groq_is_daily_quota_error(exc) is True
    with pytest.raises(RateLimitError):
        with_groq_retry(_fail, operation_name="test_daily_quota", max_attempts=4)


def test_set_protocol_payload_uses_procedure_filter() -> None:
    settings = MagicMock()
    settings.qdrant_url = "http://localhost:6333"
    settings.qdrant_timeout_seconds = 30.0
    settings.qdrant_collection = "postop_clinical_knowledge"

    with patch.object(QdrantVectorStore, "__init__", lambda self, _settings=None: None):
        store = QdrantVectorStore(settings)
        store._settings = settings
        store._client = MagicMock()
        store._client.count.return_value = MagicMock(count=3)
        store._run = lambda _name, fn: fn()

        updated = store.set_protocol_payload(
            ProcedureScenario.APPENDICITIS,
            _sample_protocol_payload(),
        )

    assert updated == 3
    store._client.set_payload.assert_called_once()


def test_generate_protocols_skips_existing(tmp_path: Path) -> None:
    store = MagicMock()
    store.list_indexed_scenarios.return_value = [ProcedureScenario.APPENDICITIS]

    retriever = MagicMock()
    llm = MagicMock()

    settings = MagicMock()
    settings.protocol_dir = tmp_path
    settings.textos_dir = tmp_path / "textos"
    settings.textos_dir.mkdir()
    (settings.textos_dir / "appendicitis").mkdir()
    settings.protocol_skip_existing = True

    existing = procedure_protocol_path(tmp_path, ProcedureScenario.APPENDICITIS)
    existing.parent.mkdir(parents=True)
    existing.write_text("{}", encoding="utf-8")

    report = generate_protocols_for_indexed_procedures(
        settings=settings,
        store=store,
        retriever=retriever,
        llm=llm,
        output_dir=tmp_path,
    )

    assert report.skipped_procedures == ["appendicitis"]
    assert report.procedures == []
    llm.generate_protocol_json.assert_not_called()


def test_generate_protocols_for_indexed_procedures(tmp_path: Path) -> None:
    store = MagicMock()
    store.list_indexed_scenarios.return_value = [ProcedureScenario.APPENDICITIS]
    store.set_protocol_payload.return_value = 4

    retriever = MagicMock()
    retriever.retrieve.return_value = ("query", [_sample_chunk()], 10.0)

    llm = MagicMock()
    llm.generate_protocol_json.return_value = PostOpProtocol(
        procedure="appendicitis",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[
            SymptomDefinition(
                id="dolor",
                question="Del 0 al 10, ¿cómo califica su dolor?",
                type="numeric",
                levels=[SymptomLevel(min=0, max=3, points=0, label="verde")],
                fuentes=["doc_apendicitis_01"],
            )
        ],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=["dolor intenso (≥8/10)"],
        source_ids=["doc_apendicitis_01"],
    )

    settings = MagicMock()
    settings.protocol_dir = tmp_path
    settings.textos_dir = tmp_path / "textos"
    settings.textos_dir.mkdir()
    (settings.textos_dir / "appendicitis").mkdir()
    settings.protocol_skip_existing = True
    settings.protocol_min_symptoms = 3
    settings.protocol_retrieval_top_k = 12
    settings.protocol_retrieval_per_query_top_k = 5
    settings.protocol_retrieval_score_threshold = 0.55
    settings.protocol_retrieval_expanded_per_query_top_k = 8
    settings.protocol_retrieval_expanded_score_threshold = 0.45
    settings.protocol_max_symptoms = 8
    settings.protocol_compact_max_chunks = 6

    report = generate_protocols_for_indexed_procedures(
        settings=settings,
        store=store,
        retriever=retriever,
        llm=llm,
        output_dir=tmp_path,
        force=True,
    )

    assert report.general_protocol_path.endswith("general/protocol.json")
    assert len(report.procedures) == 1
    assert report.procedures[0].procedure_scenario == "appendicitis"
    assert (tmp_path / "appendicitis" / "protocol.json").exists()
    saved = json.loads((tmp_path / "appendicitis" / "protocol.json").read_text(encoding="utf-8"))
    assert len(saved["symptoms"]) >= 3
    store.set_protocol_payload.assert_called_once()


def test_generate_protocol_for_procedure_falls_back_when_llm_fails(tmp_path: Path) -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = ("query", [_sample_chunk()], 10.0)

    llm = MagicMock()
    llm.generate_protocol_json.side_effect = LLMError(
        "Gemini protocol generation failed: output truncated (MAX_TOKENS)"
    )

    settings = MagicMock()
    settings.protocol_min_symptoms = 3
    settings.protocol_retrieval_top_k = 12
    settings.protocol_retrieval_per_query_top_k = 5
    settings.protocol_retrieval_score_threshold = 0.55
    settings.protocol_retrieval_expanded_per_query_top_k = 8
    settings.protocol_retrieval_expanded_score_threshold = 0.45
    settings.protocol_compact_max_chunks = 6
    settings.protocol_max_output_tokens = 8192
    settings.protocol_compact_fragment_max_chars = 600
    settings.protocol_compact_max_symptoms = 6
    settings.max_turns_per_call = 8
    settings.protocol_max_symptoms = 8

    protocol, _chunks, used_fallback = _generate_protocol_for_procedure(
        procedure_scenario=ProcedureScenario.COLORECTAL_CANCER,
        resolved_settings=settings,
        resolved_retriever=retriever,
        resolved_llm=llm,
    )

    assert used_fallback is True
    assert len(protocol.symptoms) >= 3
    assert protocol.procedure == "colorectal_cancer"


def test_generate_protocol_for_procedure_applies_general_fallback(tmp_path: Path) -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = ("query", [_sample_chunk()], 10.0)

    llm = MagicMock()
    llm.generate_protocol_json.return_value = PostOpProtocol(
        procedure="cervical_cancer",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        symptoms=[],
        thresholds=ProtocolThresholds(verde=0, amarillo=8, rojo=15),
        alert_signs=["sangrado"],
        source_ids=["doc_apendicitis_01"],
    )

    settings = MagicMock()
    settings.protocol_min_symptoms = 3
    settings.protocol_retrieval_top_k = 12
    settings.protocol_retrieval_per_query_top_k = 5
    settings.protocol_retrieval_score_threshold = 0.55
    settings.protocol_retrieval_expanded_per_query_top_k = 8
    settings.protocol_retrieval_expanded_score_threshold = 0.45
    settings.protocol_max_output_tokens = 8192
    settings.protocol_compact_max_chunks = 6
    settings.protocol_compact_fragment_max_chars = 600
    settings.protocol_compact_max_symptoms = 6
    settings.max_turns_per_call = 8
    settings.protocol_max_symptoms = 8

    protocol, _chunks, used_fallback = _generate_protocol_for_procedure(
        procedure_scenario=ProcedureScenario.CERVICAL_CANCER,
        resolved_settings=settings,
        resolved_retriever=retriever,
        resolved_llm=llm,
    )

    assert used_fallback is True
    assert len(protocol.symptoms) >= 3
    assert protocol.procedure == "cervical_cancer"
    assert llm.generate_protocol_json.call_count == 2


def test_generate_protocols_waits_between_llm_calls(tmp_path: Path, monkeypatch) -> None:
    store = MagicMock()
    store.list_indexed_scenarios.return_value = [
        ProcedureScenario.APPENDICITIS,
        ProcedureScenario.CHOLECYSTITIS,
    ]
    store.set_protocol_payload.return_value = 1

    retriever = MagicMock()
    retriever.retrieve.return_value = ("query", [_sample_chunk()], 10.0)

    llm = MagicMock()
    llm.generate_protocol_json.return_value = _complete_protocol("appendicitis")

    settings = MagicMock()
    settings.protocol_dir = tmp_path
    settings.textos_dir = tmp_path / "textos"
    settings.textos_dir.mkdir()
    (settings.textos_dir / "appendicitis").mkdir()
    (settings.textos_dir / "cholecystitis").mkdir()
    settings.protocol_skip_existing = True
    settings.protocol_min_symptoms = 3
    settings.protocol_retrieval_top_k = 12
    settings.protocol_retrieval_per_query_top_k = 5
    settings.protocol_retrieval_score_threshold = 0.55
    settings.protocol_retrieval_expanded_per_query_top_k = 8
    settings.protocol_retrieval_expanded_score_threshold = 0.45
    settings.protocol_generation_delay_seconds = 15.0
    settings.protocol_max_symptoms = 8
    settings.protocol_compact_max_chunks = 6

    sleeps: list[float] = []
    monkeypatch.setattr(
        "knowledge.protocol.generator.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    generate_protocols_for_indexed_procedures(
        settings=settings,
        store=store,
        retriever=retriever,
        llm=llm,
        output_dir=tmp_path,
        force=True,
    )

    assert llm.generate_protocol_json.call_count == 2
    assert sleeps == [15.0]


def test_generate_protocols_stops_on_daily_gemini_quota(tmp_path: Path) -> None:
    from google.api_core.exceptions import ResourceExhausted

    store = MagicMock()
    store.list_indexed_scenarios.return_value = [
        ProcedureScenario.APPENDICITIS,
        ProcedureScenario.CHOLECYSTITIS,
    ]

    retriever = MagicMock()
    retriever.retrieve.return_value = ("query", [_sample_chunk()], 10.0)

    llm = MagicMock()
    llm.generate_protocol_json.side_effect = ResourceExhausted(
        "GenerateRequestsPerDayPerProjectPerModel-FreeTier limit: 0"
    )

    settings = MagicMock()
    settings.protocol_dir = tmp_path
    settings.textos_dir = tmp_path / "textos"
    settings.textos_dir.mkdir()
    (settings.textos_dir / "appendicitis").mkdir()
    (settings.textos_dir / "cholecystitis").mkdir()
    settings.protocol_skip_existing = True
    settings.protocol_generation_delay_seconds = 0.0
    settings.protocol_min_symptoms = 3
    settings.protocol_retrieval_top_k = 12
    settings.protocol_retrieval_per_query_top_k = 5
    settings.protocol_retrieval_score_threshold = 0.55
    settings.protocol_retrieval_expanded_per_query_top_k = 8
    settings.protocol_retrieval_expanded_score_threshold = 0.45
    settings.protocol_max_symptoms = 8
    settings.protocol_compact_max_chunks = 6

    report = generate_protocols_for_indexed_procedures(
        settings=settings,
        store=store,
        retriever=retriever,
        llm=llm,
        output_dir=tmp_path,
        force=True,
    )

    assert llm.generate_protocol_json.call_count == 1
    assert len(report.errors) == 2
    assert "daily quota exhausted" in report.errors[-1]
