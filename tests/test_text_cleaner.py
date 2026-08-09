"""Tests for clinical text cleaning."""

from knowledge.ingest.text_cleaner import clean_clinical_text


def test_clean_clinical_text_removes_doi_and_urls() -> None:
    raw = "Ver artículo doi:10.1234/example y https://example.org/paper para más."
    cleaned = clean_clinical_text(raw)
    assert "doi:" not in cleaned.lower()
    assert "https://" not in cleaned
    assert "Ver artículo" in cleaned


def test_clean_clinical_text_removes_cid_artifacts() -> None:
    assert "cid:123" not in clean_clinical_text("Texto cid:12345 basura")


def test_clean_clinical_text_empty_input() -> None:
    assert clean_clinical_text("") == ""
