"""Simple recursive-character chunker. Sentence-aware where possible."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass
class Chunk:
    index: int
    text: str


def chunk_text(text: str, *, target_chars: int = 1200, overlap_chars: int = 200) -> list[Chunk]:
    """Split text into roughly target_chars chunks with overlap.

    Strategy: split on paragraphs first; within each paragraph, on sentences;
    pack greedily up to target_chars; add tail-overlap when seeding the next chunk.
    """
    if not text.strip():
        return []

    paragraphs = [p.strip() for p in _PARAGRAPH_BREAK.split(text) if p.strip()]
    units: list[str] = []
    for p in paragraphs:
        if len(p) <= target_chars:
            units.append(p)
        else:
            units.extend(s.strip() for s in _SENTENCE_BREAK.split(p) if s.strip())

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    idx = 0
    for u in units:
        u_len = len(u) + 1
        if buf and buf_len + u_len > target_chars:
            joined = " ".join(buf)
            chunks.append(Chunk(index=idx, text=joined))
            idx += 1
            tail = joined[-overlap_chars:] if overlap_chars > 0 else ""
            buf = [tail, u] if tail else [u]
            buf_len = len(tail) + 1 + u_len
        else:
            buf.append(u)
            buf_len += u_len

    if buf:
        chunks.append(Chunk(index=idx, text=" ".join(buf)))

    return chunks
