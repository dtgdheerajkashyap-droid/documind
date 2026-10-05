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
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)


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
