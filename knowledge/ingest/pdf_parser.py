"""PDF parsing and metadata extraction."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pymupdf

from core.config import Settings, get_settings
from core.exceptions import InsufficientTextError
from core.models import DocumentType, ParsedDocument, ParsedPage, ProcedureScenario
from knowledge.text_utils import compute_content_hash, normalize_text

FOLDER_TO_SCENARIO: dict[str, ProcedureScenario] = {
    "appendicitis": ProcedureScenario.APPENDICITIS,
    "cholecystitis": ProcedureScenario.CHOLECYSTITIS,
    "colorectal cancer": ProcedureScenario.COLORECTAL_CANCER,
    "breast_cancer": ProcedureScenario.BREAST_CANCER,
    "total joint replacement": ProcedureScenario.TOTAL_JOINT_REPLACEMENT,
}

GENERAL_KEYWORDS: tuple[str, ...] = (
    "cuidado estandarizado",
    "nursing review",
    "standardized",
    "general care",
    "postoperative care for patients",
)

DOCUMENT_TYPE_RULES: tuple[tuple[tuple[str, ...], DocumentType], ...] = (
    (("guia", "guía", "guide", "manual", "instructivo"), DocumentType.GUIDE),
    (("protocol", "protocolo", "estandar", "estándar", "standard"), DocumentType.PROTOCOL),
    (("plan de cuidado", "care plan", "plan de manejo"), DocumentType.CARE_PLAN),
    (
        ("patient", "paciente", "recovery after", "enhancing your recovery"),
        DocumentType.PATIENT_INSTRUCTION,
    ),
    (
        ("analysis", "study", "cohort", "review", "syndrome", "outcomes", "complications"),
        DocumentType.PAPER,
    ),
)


def _detect_language(text: str) -> str:
    sample = text[:4000].lower()
    spanish_markers = (" de ", " la ", " el ", " que ", " con ", " para ", " dolor ", " paciente ")
    english_markers = (" the ", " and ", " with ", " patient ", " postoperative ", " surgery ")
    es_score = sum(sample.count(marker) for marker in spanish_markers)
    en_score = sum(sample.count(marker) for marker in english_markers)
    if es_score == en_score:
        return "es" if re.search(r"[áéíóúñ]", sample) else "en"
    return "es" if es_score > en_score else "en"


def _infer_document_type(file_name: str) -> DocumentType:
    lowered = file_name.lower()
    for keywords, doc_type in DOCUMENT_TYPE_RULES:
        if any(keyword in lowered for keyword in keywords):
            return doc_type
    return DocumentType.OTHER


def _is_general_document(file_name: str, document_type: DocumentType) -> bool:
    lowered = file_name.lower()
    if document_type in {DocumentType.GENERAL, DocumentType.PROTOCOL}:
        return True
    return any(keyword in lowered for keyword in GENERAL_KEYWORDS)


def _build_source_id(file_path: Path) -> str:
    digest = hashlib.sha256(str(file_path.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"src_{digest}"


def map_folder_to_scenario(folder_name: str) -> ProcedureScenario:
    scenario = FOLDER_TO_SCENARIO.get(folder_name.lower())
    if scenario is None:
        raise ValueError(f"Unknown procedure folder: {folder_name}")
    return scenario


def parse_pdf(file_path: Path, settings: Settings | None = None) -> ParsedDocument:
    """Extract text page-by-page from a PDF and attach metadata."""
    settings = settings or get_settings()
    file_path = file_path.resolve()
    parent_folder = file_path.parent.name
    procedure_scenario = map_folder_to_scenario(parent_folder)
    document_type = _infer_document_type(file_path.name)
    is_general = _is_general_document(file_path.name, document_type)

    pages: list[ParsedPage] = []
    with pymupdf.open(file_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            raw_text = page.get_text("text") or ""
            cleaned = normalize_text(raw_text)
            if cleaned:
                pages.append(ParsedPage(page_number=page_index + 1, text=cleaned))

    full_text = " ".join(page.text for page in pages)
    if len(full_text) < settings.min_document_chars:
        raise InsufficientTextError(
            f"Insufficient text in {file_path.name}: {len(full_text)} chars"
        )

    return ParsedDocument(
        source_id=_build_source_id(file_path),
        file_path=str(file_path),
        file_name=file_path.name,
        procedure_scenario=procedure_scenario,
        document_type=document_type,
        language=_detect_language(full_text),
        content_hash=compute_content_hash(full_text),
        page_count=len(pages),
        char_count=len(full_text),
        is_general=is_general,
        pages=pages,
    )


def iter_pdf_files(textos_dir: Path) -> list[Path]:
    return sorted(textos_dir.rglob("*.pdf"))
