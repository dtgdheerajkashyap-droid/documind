"""Split page text into overlapping, boundary-aware chunks.

Chunks never span pages, so every citation points at exactly one page.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.pdf_parser import PageText

# Preferred split points, strongest first.
_SEPARATORS = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


@dataclass(frozen=True, slots=True)
class TextChunk:
    text: str
    page_number: int
    chunk_index: int  # position within the whole document
    char_start: int  # offset within the page text


def _find_break(text: str, start: int, end: int, min_size: int) -> int:
    """Best split position in text[start:end], not earlier than start + min_size."""
    window = text[start:end]
    for sep in _SEPARATORS:
        pos = window.rfind(sep)
        if pos >= min_size:
            return start + pos + len(sep)
    return end  # no natural boundary: hard cut


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[tuple[int, str]]:
    """Split `text` into (offset, chunk) pairs of at most `chunk_size` characters.

    Consecutive chunks share roughly `chunk_overlap` characters so a sentence cut
    at a boundary still appears whole in one of the two neighbouring chunks.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be in [0, chunk_size)")

    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [(0, text)]

    pieces: list[tuple[int, str]] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            end = _find_break(text, start, end, min_size=chunk_size // 2)
        piece = text[start:end].strip()
        if piece:
            pieces.append((start, piece))
        if end >= length:
            break

        # Step back by the overlap, then forward to a word boundary so the next
        # chunk does not begin mid-word.
        next_start = max(end - chunk_overlap, start + 1)
        if 0 < next_start < end and not text[next_start - 1].isspace():
            space = text.find(" ", next_start, end)
            if space != -1:
                next_start = space + 1
        start = next_start
    return pieces


def chunk_pages(pages: list[PageText], chunk_size: int, chunk_overlap: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page in pages:
        for offset, text in split_text(page.text, chunk_size, chunk_overlap):
            chunks.append(
                TextChunk(
                    text=text,
                    page_number=page.page_number,
                    chunk_index=len(chunks),
                    char_start=offset,
                )
            )
    return chunks
