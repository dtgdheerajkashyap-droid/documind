from itertools import pairwise

import pytest

from app.services.chunking import chunk_pages, split_text
from app.services.pdf_parser import PageText, clean_text

LOREM = (
    "Retrieval-augmented generation grounds a language model in external documents. "
    "First the documents are split into chunks. Each chunk is embedded into a vector. "
    "At question time the most similar chunks are retrieved and passed to the model. "
    "The model then answers using only that context, citing its sources. "
) * 8


def test_short_text_is_a_single_chunk() -> None:
    assert split_text("  Hello world.  ", chunk_size=100, chunk_overlap=10) == [(0, "Hello world.")]


def test_empty_text_yields_no_chunks() -> None:
    assert split_text("   \n\n ", chunk_size=100, chunk_overlap=10) == []


def test_chunks_respect_max_size() -> None:
    pieces = split_text(LOREM, chunk_size=200, chunk_overlap=40)
    assert len(pieces) > 1
    assert all(len(text) <= 200 for _, text in pieces)


def test_chunks_cover_whole_text_in_order() -> None:
    pieces = split_text(LOREM, chunk_size=200, chunk_overlap=40)
    offsets = [offset for offset, _ in pieces]
    assert offsets == sorted(offsets)
    assert pieces[0][0] == 0
    assert LOREM.strip().endswith(pieces[-1][1])


def test_consecutive_chunks_overlap() -> None:
    pieces = split_text(LOREM, chunk_size=200, chunk_overlap=60)
    for (_, previous), (_, current) in pairwise(pieces):
        # The start of each chunk should appear at the end of the previous one.
        assert current[:15] in previous


def test_prefers_sentence_boundaries() -> None:
    pieces = split_text(LOREM, chunk_size=200, chunk_overlap=0)
    assert all(text.endswith(".") for _, text in pieces[:-1])


def test_chunks_do_not_start_mid_word() -> None:
    text = " ".join(f"word{i}" for i in range(400))
    pieces = split_text(text, chunk_size=120, chunk_overlap=30)
    for _, piece in pieces:
        assert piece.split()[0].startswith("word")


def test_hard_cut_when_no_boundary_exists() -> None:
    pieces = split_text("x" * 1000, chunk_size=300, chunk_overlap=50)
    assert all(len(p) <= 300 for _, p in pieces)
    assert len(pieces) >= 4


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, 100), (100, 150), (100, -1)])
def test_invalid_parameters_raise(size: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="chunk_"):
        split_text("some text", chunk_size=size, chunk_overlap=overlap)


def test_chunk_pages_keeps_page_numbers_and_global_index() -> None:
    pages = [PageText(1, LOREM), PageText(2, ""), PageText(3, "A short final page.")]
    chunks = chunk_pages(pages, chunk_size=300, chunk_overlap=50)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert {c.page_number for c in chunks} == {1, 3}
    assert chunks[-1].page_number == 3
    assert chunks[-1].text == "A short final page."


def test_clean_text_fixes_common_pdf_artifacts() -> None:
    raw = "The ﬁrst exam-\nple wraps\nacross lines.\n\n\n\nNew   paragraph\there."
    assert clean_text(raw) == "The first example wraps across lines.\n\nNew paragraph here."
