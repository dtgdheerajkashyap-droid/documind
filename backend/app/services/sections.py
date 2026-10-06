"""Numbered sections of a document ("Program 4", "Experiment 2", "Chapter 3").

Lab manuals and workbooks are mostly a sequence of numbered parts whose body is code
or tables. Only the first chunk of a part says which part it is, so "explain Program 4"
would otherwise reach the heading and miss the code below it. Sections are found from
the chunk texts alone (in document order), so they work for documents indexed before
this existed and need no extra storage.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from app.services import lexical

# A heading starts a paragraph: a unit word, a number, then the part's title.
_HEADING = re.compile(
    r"^(?P<kind>program|programme|experiment|exercise|practical|assignment|lab|week"
    r"|chapter|unit|module|lesson|task|project)\s*(?:no\.?\s*|#\s*)?(?P<num>\d{1,3})\b"
    r"\s*[:.)\-–—]?\s*(?P<rest>.*)",
    re.IGNORECASE | re.MULTILINE,
)
# The title is the heading's first sentence, so code that follows it on the same line
# ("... time series data. %% 1. Simulated ...") is left out.
_SENTENCE_END = re.compile(r"(?<=[A-Za-z)])[.?!](?=\s|$)")
MAX_TITLE_CHARS = 160
# Chunks with less text than this (a running page header on a blank page) carry nothing.
MIN_CONTENT_CHARS = 40
# A chunk with this many headings is a table of contents.
MAX_HEADINGS_PER_CHUNK = 3


@dataclass(frozen=True, slots=True)
class Section:
    kind: str  # normalised unit word: "program", "experiment", ... share one kind
    number: str
    title: str  # "Program 4: Build and demonstrate an autoencoder network ..."
    chunks: tuple[int, ...]  # positions in the chunk list, in document order

    @property
    def label(self) -> tuple[str, str]:
        return self.kind, self.number


def find_sections(texts: list[str]) -> list[Section]:
    """Numbered sections in a document's chunks (given in document order).

    A section runs from the chunk with its heading to the chunk before the next heading
    of the same kind. The last one of a kind has no such end, so it is cut at the
    typical length of the others (a manual's appendix should not join Program 8).
    """
    headings: list[tuple[int, str, str, str]] = []  # (chunk, kind, number, title)
    seen: set[tuple[str, str]] = set()
    for position, text in enumerate(texts):
        matches = list(_HEADING.finditer(text))
        if len(matches) >= MAX_HEADINGS_PER_CHUNK:
            continue  # a table of contents lists the parts; it does not start them
        for match in matches:
            kind = lexical.tokenize(match["kind"])[0]
            number = str(int(match["num"]))
            # Repeats (a table of contents, an overlapping chunk) are not new sections.
            if (kind, number) in seen:
                continue
            seen.add((kind, number))
            headings.append((position, kind, number, _title(match)))

    sections: list[Section] = []
    for i, (start, kind, number, title) in enumerate(headings):
        following = [h[0] for h in headings[i + 1 :] if h[1] == kind]
        end = following[0] if following else len(texts)
        chunks = tuple(p for p in range(start, max(end, start + 1)) if _has_content(texts[p]))
        sections.append(Section(kind, number, title, chunks or (start,)))

    for kind in {s.kind for s in sections}:
        same = [s for s in sections if s.kind == kind]
        if len(same) > 1:
            typical = round(statistics.median(len(s.chunks) for s in same[:-1]))
            last = same[-1]
            sections[sections.index(last)] = Section(
                last.kind, last.number, last.title, last.chunks[: max(typical, 1)]
            )
    return sections


def chunk_titles(texts: list[str]) -> list[str | None]:
    """For each chunk, the title of the section it continues (None for heading chunks).

    Used as context: "MiniBatchSize = 4" means little until you know it is in
    "Program 5: ... classification of textual documents".
    """
    titles: list[str | None] = [None] * len(texts)
    for section in find_sections(texts):
        for position in section.chunks[1:]:
            titles[position] = section.title
    return titles


def embedding_texts(texts: list[str]) -> list[str]:
    """Chunk texts prefixed with the title of the section they continue, for embedding."""
    return [
        f"{title}\n\n{text}" if title else text
        for title, text in zip(chunk_titles(texts), texts, strict=True)
    ]


def _title(match: re.Match[str]) -> str:
    rest = match["rest"].strip()
    end = _SENTENCE_END.search(rest)
    if end:
        rest = rest[: end.end()]
    title = f"{match['kind'].capitalize()} {int(match['num'])}: {rest}".strip().rstrip(":")
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS].rsplit(" ", 1)[0] + " ..."
    return title


def _has_content(text: str) -> bool:
    return len(text.strip()) >= MIN_CONTENT_CHARS
