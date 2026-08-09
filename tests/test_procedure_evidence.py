from agent.decision.procedure_evidence import has_procedure_specific_evidence
from core.models import DocumentType, ProcedureScenario, RetrievedChunk


def _chunk(*, scenario: ProcedureScenario) -> RetrievedChunk:
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
        score=0.9,
    )


def test_has_procedure_specific_evidence_when_matching_chunk_exists() -> None:
    chunks = [_chunk(scenario=ProcedureScenario.APPENDICITIS)]
    assert has_procedure_specific_evidence(chunks, ProcedureScenario.APPENDICITIS) is True


def test_has_procedure_specific_evidence_false_for_other_without_chunks() -> None:
    assert has_procedure_specific_evidence([], ProcedureScenario.OTHER) is False


def test_has_procedure_specific_evidence_true_for_other_with_chunks() -> None:
    chunks = [_chunk(scenario=ProcedureScenario.OTHER)]
    assert has_procedure_specific_evidence(chunks, ProcedureScenario.OTHER) is True


def test_has_procedure_specific_evidence_false_when_scenario_differs() -> None:
    chunks = [_chunk(scenario=ProcedureScenario.CHOLECYSTITIS)]
    assert has_procedure_specific_evidence(chunks, ProcedureScenario.APPENDICITIS) is False


def test_has_procedure_specific_evidence_false_when_empty() -> None:
    assert has_procedure_specific_evidence([], ProcedureScenario.CHOLECYSTITIS) is False
