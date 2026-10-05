"""PDF text extraction with PyMuPDF."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.core.errors import IngestionError

PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True, slots=True)
class PageText:
    page_number: int  # 1-based, as shown to users
    text: str


_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_INLINE_WS = re.compile(r"[ \t\r\f\v ]+")
_MANY_BREAKS = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Normalise raw PDF text while keeping paragraph boundaries.

    - NFKC normalisation (turns ligatures such as "ﬁ" into "fi")
    - re-joins words hyphenated across line breaks ("exam-\\nple" -> "example")
    - joins wrapped lines inside a paragraph, keeps blank-line paragraph breaks
    - collapses runs of whitespace
    """
    text = unicodedata.normalize("NFKC", text).replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    paragraphs = re.split(r"\n\s*\n", text)
    cleaned = []
    for paragraph in paragraphs:
        joined = _INLINE_WS.sub(" ", paragraph.replace("\n", " ")).strip()
        if joined:
            cleaned.append(joined)
    return _MANY_BREAKS.sub("\n\n", "\n\n".join(cleaned))


def extract_pages(path: Path | str) -> list[PageText]:
    """Return the cleaned text of every page. Pages without text are kept (empty)."""
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise IngestionError(f"Could not open PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise IngestionError("PDF is password-protected.")
        return [
            PageText(page_number=index + 1, text=clean_text(_page_text(page)))
            for index, page in enumerate(doc)
        ]


def _page_text(page: pymupdf.Page) -> str:
    """Join text blocks into paragraphs.

    PyMuPDF often returns one block per visual line, so blocks are merged unless
    the vertical gap between them is larger than about half a line, which is
    what separates real paragraphs.
    """
    blocks = [b for b in page.get_text("blocks", sort=True) if b[6] == 0]  # 0 == text
    parts: list[str] = []
    prev_bottom: float | None = None
    prev_line_height = 0.0
    for _x0, y0, _x1, y1, text, *_ in blocks:
        text = text.strip()
        if not text:
            continue
        if prev_bottom is not None:
            gap = y0 - prev_bottom
            parts.append("\n\n" if gap > max(3.0, 0.5 * prev_line_height) else "\n")
        parts.append(text)
        prev_bottom = y1
        prev_line_height = (y1 - y0) / max(1, text.count("\n") + 1)
    return "".join(parts)


def looks_like_pdf(header: bytes) -> bool:
    return header.startswith(PDF_MAGIC)
