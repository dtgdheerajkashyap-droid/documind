from pathlib import Path

from app.core.container import AppContainer
from tests.conftest import ingest_document, make_pdf


def _ingest(container: AppContainer, path: Path) -> str:
    return str(ingest_document(container, path))


def test_retrieves_most_relevant_chunk_first(container: AppContainer, sample_pdf: Path) -> None:
    _ingest(container, sample_pdf)

    results = container.retriever.retrieve("How many days of paid vacation do baristas get?", 3)

    assert results[0].page == 3
    assert "20 days of paid vacation" in results[0].text
    assert results[0].filename == sample_pdf.name


def test_top_k_limits_results(container: AppContainer, sample_pdf: Path) -> None:
    _ingest(container, sample_pdf)
    assert len(container.retriever.retrieve("coffee", 1)) == 1


def test_document_filter_restricts_results(
    container: AppContainer, sample_pdf: Path, tmp_path: Path
) -> None:
    orion_id = _ingest(container, sample_pdf)
    other = make_pdf(
        tmp_path / "garden.pdf", ["Tomato plants need six hours of sun and weekly watering."]
    )
    garden_id = _ingest(container, other)

    unfiltered = container.retriever.retrieve("tomato watering sun", 5)
    assert unfiltered[0].document_id == garden_id

    filtered = container.retriever.retrieve("tomato watering sun", 5, document_ids=[orion_id])
    assert filtered
    assert {r.document_id for r in filtered} == {orion_id}


def test_unrelated_query_scores_low(container: AppContainer, sample_pdf: Path) -> None:
    _ingest(container, sample_pdf)
    results = container.retriever.retrieve("quantum chromodynamics gluon lattice", 3)
    assert results[0].score < container.settings.retrieval_min_score


def test_empty_index_returns_nothing(container: AppContainer) -> None:
    assert container.retriever.retrieve("anything", 5) == []


LAB_CODE = (
    "%% Step 1: load data\nX = rand(100, 1); Y = zeros(1, 100);\n"
    "for i = 1:100\n  Y(i) = X(i) * 2 + 1;\nend\nplot(1:100, Y); disp(Y(1));\n"
)


def test_numbered_program_found_even_when_its_chunk_is_mostly_code(
    container: AppContainer, tmp_path: Path
) -> None:
    pages = [
        f"Program {n}: {title}\n{LAB_CODE}"
        for n, title in [
            (1, "Generate word embeddings for a corpus."),
            (2, "Classify handwritten digits."),
            (3, "Build a convolutional network."),
        ]
    ]
    _ingest(container, make_pdf(tmp_path / "lab_manual.pdf", pages))

    results = container.retriever.retrieve("explain the first program", 3)

    assert results[0].page == 1
    assert results[0].text.startswith("Program 1:")
    assert results[0].keyword_match
    assert not any(r.keyword_match for r in results[1:])


def test_named_program_returns_its_whole_section_in_order(
    container: AppContainer, tmp_path: Path
) -> None:
    pages = [
        "Program 1: Generate word embeddings for a corpus.\n" + LAB_CODE,
        "Program 2: Classify handwritten digits.\n" + LAB_CODE,
        "%% Step 4: evaluate\nacc = mean(YPred == YTest);\n" + LAB_CODE,
        "Output: Test Accuracy: 91.60% Validation Accuracy: 92.29%",
        "Program 3: Build a convolutional network.\n" + LAB_CODE,
    ]
    _ingest(container, make_pdf(tmp_path / "lab_manual.pdf", pages))

    results = container.retriever.retrieve("Explain Program 2 step by step", 3)

    section = [r for r in results if r.keyword_match]
    assert sorted({r.page for r in section}) == [2, 3, 4]
    assert [r.chunk_index for r in section] == sorted(r.chunk_index for r in section)
    assert section[0].text.startswith("Program 2:")
    assert not any(r.page in (1, 5) and r.keyword_match for r in results)
