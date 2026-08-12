"""Remove bibliographic noise and PDF artifacts from extracted clinical text."""

from __future__ import annotations

import re

# Patterns removed or replaced during clinical text cleaning.
_DOI_PATTERN = re.compile(r"\bdoi:\s*\S+", re.IGNORECASE)
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_CID_PATTERN = re.compile(r"\bcid:\d+", re.IGNORECASE)
_BIBLIO_PATTERN = re.compile(
    r"\b(?:vol\.?\s*\d+|pp\.?\s*\d+|issn\s*\S+|isbn\s*\S+)\b",
    re.IGNORECASE,
)
_REPEATED_PUNCT = re.compile(r"(\.{3,}|_{3,}|-{3,})")
_REPLACEMENT_CHAR = "\ufffd"
_MULTI_SPACE = re.compile(r"\s+")


def clean_clinical_text(text: str) -> str:
    """Strip common PDF junk while preserving clinical prose."""
    if not text:
        return ""
    cleaned = text.replace(_REPLACEMENT_CHAR, " ")
    cleaned = _DOI_PATTERN.sub(" ", cleaned)
    cleaned = _URL_PATTERN.sub(" ", cleaned)
    cleaned = _CID_PATTERN.sub(" ", cleaned)
    cleaned = _BIBLIO_PATTERN.sub(" ", cleaned)
    cleaned = _REPEATED_PUNCT.sub(" ", cleaned)
    return _MULTI_SPACE.sub(" ", cleaned).strip()
