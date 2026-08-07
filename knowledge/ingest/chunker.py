"""Token-based document chunking."""

from __future__ import annotations

import uuid

from core.config import Settings, get_settings
from core.models import ParsedDocument, TextChunk
from knowledge.text_utils import normalize_text


class TokenChunker:
    """Split documents into overlapping token windows."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tokenizer = None

    def _get_tokenizer(self):
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self._settings.embedding_model)
        return self._tokenizer

    def _encode(self, text: str) -> list[int]:
        return self._get_tokenizer().encode(text, add_special_tokens=False)

    def _decode(self, token_ids: list[int]) -> str:
        return self._get_tokenizer().decode(token_ids, skip_special_tokens=True)

    def chunk_document(self, document: ParsedDocument) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        chunk_size = self._settings.chunk_size_tokens
        overlap = self._settings.chunk_overlap_tokens
        step = max(chunk_size - overlap, 1)

        page_cursor = 0
        page_boundaries: list[tuple[int, int]] = []
        for page in document.pages:
            tokens = self._encode(page.text)
            if not tokens:
                continue
            start = page_cursor
            end = page_cursor + len(tokens)
            page_boundaries.append((start, end, page.page_number))
            page_cursor = end

        if not page_boundaries:
            return chunks

        all_tokens: list[int] = []
        for page in document.pages:
            all_tokens.extend(self._encode(page.text))

        chunk_index = 0
        for start in range(0, len(all_tokens), step):
            end = min(start + chunk_size, len(all_tokens))
            token_window = all_tokens[start:end]
            if not token_window:
                continue

            text = normalize_text(self._decode(token_window))
            if not text:
                continue

            page_start, page_end = self._resolve_page_range(start, end, page_boundaries)
            chunks.append(
                TextChunk(
                    chunk_id=str(uuid.uuid4()),
                    source_id=document.source_id,
                    text=text,
                    token_count=len(token_window),
                    chunk_index=chunk_index,
                    page_start=page_start,
                    page_end=page_end,
                    procedure_scenario=document.procedure_scenario,
                    document_type=document.document_type,
                    language=document.language,
                    file_name=document.file_name,
                    is_general=document.is_general,
                )
            )
            chunk_index += 1
            if end >= len(all_tokens):
                break

        return chunks

    @staticmethod
    def _resolve_page_range(
        token_start: int,
        token_end: int,
        page_boundaries: list[tuple[int, int, int]],
    ) -> tuple[int, int]:
        pages: list[int] = []
        for boundary_start, boundary_end, page_number in page_boundaries:
            if token_end <= boundary_start:
                continue
            if token_start >= boundary_end:
                continue
            pages.append(page_number)
        if not pages:
            return page_boundaries[0][2], page_boundaries[-1][2]
        return min(pages), max(pages)
