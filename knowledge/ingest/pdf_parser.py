"""PDF parsing and metadata extraction."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf

from core.config import Settings, get_settings
from core.exceptions import InsufficientTextError
from core.models import DocumentType, ParsedDocument, ParsedPage, ProcedureScenario
from core.scenarios import map_folder_to_scenario
from knowledge.ingest.pdf_ocr import extract_page_text
from knowledge.text_utils import compute_content_hash, normalize_clinical_text

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
    import re

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


def _build_source_id(file_path: Path) -> str:
    digest = hashlib.sha256(str(file_path.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"src_{digest}"


def parse_pdf(
    file_path: Path,
    settings: Settings | None = None,
    *,
    procedure_scenario: ProcedureScenario | None = None,
) -> ParsedDocument:
    """Extract text page-by-page from a PDF and attach metadata."""
    settings = settings or get_settings()
    file_path = file_path.resolve()
    if procedure_scenario is None:
        procedure_scenario = map_folder_to_scenario(file_path.parent.name)
    document_type = _infer_document_type(file_path.name)

    pages: list[ParsedPage] = []
    with pymupdf.open(file_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            cleaned = extract_page_text(
                page,
                ocr_enabled=settings.ocr_enabled,
                ocr_languages=settings.ocr_languages,
                ocr_dpi=settings.ocr_dpi,
                ocr_min_chars=settings.ocr_min_chars,
            )
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
        pages=pages,
    )


def extract_document_excerpt(file_path: Path, *, max_chars: int = 3000) -> str:
    """Return normalized text from the first pages for category validation."""
    settings = get_settings()
    parts: list[str] = []
    with pymupdf.open(file_path) as document:
        for page_index in range(min(3, document.page_count)):
            page = document.load_page(page_index)
            cleaned = extract_page_text(
                page,
                ocr_enabled=settings.ocr_enabled,
                ocr_languages=settings.ocr_languages,
                ocr_dpi=settings.ocr_dpi,
                ocr_min_chars=settings.ocr_min_chars,
            )
            if cleaned:
                parts.append(cleaned)
            if sum(len(part) for part in parts) >= max_chars:
                break
    return normalize_clinical_text(" ".join(parts))[:max_chars]


def iter_pdf_files(textos_dir: Path) -> list[Path]:
    return sorted(textos_dir.rglob("*.pdf"))
