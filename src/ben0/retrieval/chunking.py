"""Chunking helpers for retrieval indexing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TextChunk:
    chunk_index: int
    text: str
    char_start: int
    char_end: int


def chunk_text(text: str, *, size: int = 450, overlap: int = 75) -> list[TextChunk]:
    """Split text into moderately overlapping retrieval chunks."""
    if not text or not text.strip():
        return []

    cleaned = " ".join(text.split())
    chunks: list[TextChunk] = []
    start = 0
    total = len(cleaned)
    idx = 0

    while start < total:
        end = min(start + size, total)
        if end < total:
            while end > start and cleaned[end - 1] not in {" ", ".", ";", ","}:
                end -= 1
            if end == start:
                end = min(start + size, total)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(TextChunk(idx, chunk, start, end))
            idx += 1
        if end >= total:
            break
        start = max(end - overlap, 0)

    return chunks
