from pathlib import Path

import pytest

from core.exceptions import InsufficientTextError
from core.models import ProcedureScenario
from core.scenarios import map_folder_to_scenario
from knowledge.ingest.pdf_parser import parse_pdf
from knowledge.text_utils import compute_content_hash, normalize_text


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("hola   mundo\n\npostop") == "hola mundo postop"


def test_same_content_produces_same_hash() -> None:
    first = compute_content_hash("Paciente  con   dolor")
    second = compute_content_hash("paciente con dolor")
    assert first == second


def test_map_folder_to_scenario_handles_spaces() -> None:
    assert map_folder_to_scenario("colorectal cancer") == ProcedureScenario.COLORECTAL_CANCER
    assert map_folder_to_scenario("Otro") == ProcedureScenario.OTHER
    assert map_folder_to_scenario("cuello uterino") == ProcedureScenario.CERVICAL_CANCER
    assert map_folder_to_scenario("breast_cancer") == ProcedureScenario.CERVICAL_CANCER


def test_parse_pdf_skips_insufficient_text(tmp_path: Path) -> None:
    import pymupdf

    scenario_dir = tmp_path / "Appendicitis"
    scenario_dir.mkdir()
    target = scenario_dir / "blank.pdf"

    with pymupdf.open() as document:
        document.new_page()
        document.save(target)

    with pytest.raises(InsufficientTextError):
        parse_pdf(target)


def test_parse_pdf_extracts_metadata() -> None:
    pdf_dir = Path("dataset/textos/cholecystitis")
    pdfs = list(pdf_dir.glob("*.pdf"))
    if not pdfs:
        pytest.skip("No PDF fixtures available")

    document = parse_pdf(pdfs[0])
    assert document.procedure_scenario == ProcedureScenario.CHOLECYSTITIS
    assert document.page_count > 0
    assert document.char_count >= 200
    assert document.source_id.startswith("src_")
