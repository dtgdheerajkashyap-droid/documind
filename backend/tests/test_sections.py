from app.services import sections

CODE = "x = rand(100, 1); y = zeros(1, 100); for i = 1:100 y(i) = x(i) * 2; end; plot(y);"


def _manual() -> list[str]:
    return [
        "Lab Manual. Contents: Program 1 Embeddings, Program 2 Digits, Program 3 CNN.",
        "Program 1: Generate word embeddings for a corpus. %% 1. Load the text",
        f"%% Step 2: train {CODE}",
        "Page 4",  # running header of a blank page
        f"%% Step 3: evaluate {CODE}",
        "Program 2: Classify handwritten digits.\n\nX = load('digits');",
        f"%% Step 2: train {CODE}",
        "Program 3: Build a convolutional network.",
        f"%% Step 2: train {CODE}",
        f"%% Step 3: evaluate {CODE}",
        "Sample Viva Questions. 1. What is an embedding? An embedding is a vector.",
        "2. What is softmax? It turns scores into probabilities over the classes.",
    ]


def test_sections_run_from_heading_to_the_next_heading_of_the_same_kind() -> None:
    found = sections.find_sections(_manual())

    assert [s.label for s in found] == [("<unit>", "1"), ("<unit>", "2"), ("<unit>", "3")]
    assert found[0].chunks == (1, 2, 4)  # skips the near-empty chunk 3
    assert found[1].chunks == (5, 6)


def test_table_of_contents_does_not_start_sections() -> None:
    assert sections.find_sections(_manual())[0].chunks[0] == 1


def test_last_section_is_cut_at_the_typical_length() -> None:
    # Programs 1 and 2 span 3 and 2 chunks, so Program 3 keeps 2 or 3, not the viva pages.
    assert sections.find_sections(_manual())[2].chunks[-1] <= 9


def test_title_is_the_heading_sentence() -> None:
    found = sections.find_sections(_manual())
    assert found[0].title == "Program 1: Generate word embeddings for a corpus."
    assert found[1].title == "Program 2: Classify handwritten digits."


def test_heading_variants() -> None:
    texts = ["Experiment No. 03 - Ohm's law. Measure V and I.", "Week 2: Sorting"]
    found = sections.find_sections(texts)
    assert [(s.label, s.title) for s in found] == [
        (("<unit>", "3"), "Experiment 3: Ohm's law."),
        (("week", "2"), "Week 2: Sorting"),
    ]


def test_continuation_chunks_carry_the_title_for_embedding() -> None:
    texts = _manual()
    titles = sections.chunk_titles(texts)
    assert titles[1] is None  # the heading chunk already says it
    assert titles[2] == "Program 1: Generate word embeddings for a corpus."
    assert titles[0] is None

    embedded = sections.embedding_texts(texts)
    assert embedded[2].startswith("Program 1: Generate word embeddings")
    assert embedded[2].endswith(texts[2])
    assert embedded[1] == texts[1]


def test_no_headings_no_sections() -> None:
    assert sections.find_sections(["Plain policy text.", "More text."]) == []
