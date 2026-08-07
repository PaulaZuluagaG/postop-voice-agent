"""Text normalization utilities."""

import hashlib
import re
import unicodedata


def normalize_text(text: str) -> str:
    """Normalize whitespace and unicode for embedding and hashing."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\x00", " ")
    normalized = re.sub(r"[\u200b-\u200d\ufeff]", "", normalized)
    normalized = re.sub(r"-\n", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def compute_content_hash(text: str) -> str:
    """Return SHA-256 hex digest of normalized text."""
    payload = normalize_text(text).lower().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
