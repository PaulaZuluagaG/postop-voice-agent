from agent.decision.procedure_evidence import has_procedure_specific_evidence
from core.models import DocumentType, ProcedureScenario, RetrievedChunk


def _chunk(
    *,
    scenario: ProcedureScenario,
    is_general: bool = False,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-1",
        source_id="src_test",
        text="Texto de prueba.",
        token_count=10,
        chunk_index=0,
        page_start=1,
        page_end=1,
        procedure_scenario=scenario,
        document_type=DocumentType.GUIDE,
        language="es",
        file_name="guia.pdf",
        is_general=is_general,
        score=0.9,
    )


def test_has_procedure_specific_evidence_when_matching_chunk_exists() -> None:
    chunks = [_chunk(scenario=ProcedureScenario.APPENDICITIS)]
    assert has_procedure_specific_evidence(chunks, ProcedureScenario.APPENDICITIS) is True


def test_has_procedure_specific_evidence_false_for_general_scenario() -> None:
    chunks = [_chunk(scenario=ProcedureScenario.APPENDICITIS)]
    assert has_procedure_specific_evidence(chunks, ProcedureScenario.GENERAL) is False


def test_has_procedure_specific_evidence_false_for_general_chunks_only() -> None:
    chunks = [_chunk(scenario=ProcedureScenario.APPENDICITIS, is_general=True)]
    assert has_procedure_specific_evidence(chunks, ProcedureScenario.APPENDICITIS) is False


def test_has_procedure_specific_evidence_false_when_empty() -> None:
    assert has_procedure_specific_evidence([], ProcedureScenario.CHOLECYSTITIS) is False
