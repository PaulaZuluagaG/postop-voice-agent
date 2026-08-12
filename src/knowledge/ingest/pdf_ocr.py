"""OCR fallback for scanned PDF pages via PyMuPDF + Tesseract."""

from __future__ import annotations

import logging
import shutil
from functools import lru_cache

import pymupdf

from knowledge.ingest.text_cleaner import clean_clinical_text
from knowledge.text_utils import normalize_text

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def page_needs_ocr(page: pymupdf.Page, *, min_chars: int = 80) -> bool:
    """True when a page looks scanned: images present and little native text."""
    native = normalize_text(page.get_text("text") or "")
    if len(native) >= min_chars:
        return False
    return bool(page.get_images(full=True))


def extract_page_text(
    page: pymupdf.Page,
    *,
    ocr_enabled: bool,
    ocr_languages: str,
    ocr_dpi: int,
    ocr_min_chars: int,
) -> str:
    """Extract page text, applying OCR when native extraction is insufficient."""
    native = normalize_text(page.get_text("text") or "")
    if len(native) >= ocr_min_chars or not ocr_enabled:
        return clean_clinical_text(native)

    if not page_needs_ocr(page, min_chars=ocr_min_chars):
        return clean_clinical_text(native)

    if not tesseract_available():
        logger.debug("Tesseract not installed; skipping OCR for page %s", page.number + 1)
        return clean_clinical_text(native)

    try:
        text_page = page.get_textpage_ocr(language=ocr_languages, dpi=ocr_dpi, full=True)
        ocr_text = normalize_text(page.get_text("text", textpage=text_page) or "")
        if len(ocr_text) > len(native):
            return clean_clinical_text(ocr_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed on page %s: %s", page.number + 1, exc)

    return clean_clinical_text(native)
