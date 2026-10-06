from app.services import lexical

CODE = "x = zeros(1, n); for i = 1:n y(i) = x(i) * 2; end plot(1:n, y); disp(1)"


def test_query_terms_normalise_ordinals_units_and_question_words() -> None:
    assert lexical.query_terms("Explain the first program") == ["1", "<unit>"]
    assert lexical.query_terms("give the code for the 2nd experiment") == ["cod", "2", "<unit>"]
    assert lexical.query_terms("what is program number 03?") == ["<unit>", "3"]


def test_numbered_label_outranks_code_full_of_the_same_number() -> None:
    texts = [
        f"Program 2: Train a classifier. {CODE}",
        f"Program 1: Generate word embeddings. {CODE}",
        f"Program 3: Build an autoencoder. {CODE}",
    ]
    hits = lexical.rank("explain the first program", texts, limit=3)

    assert hits[0].index == 1
    assert hits[0].strong
    assert not any(h.strong for h in hits[1:])


def test_label_allows_a_word_in_between() -> None:
    [hit] = lexical.rank("experiment 4", ["Experiment No. 4: Edge detection"], limit=1)
    assert hit.strong


def test_identifier_is_strong() -> None:
    hits = lexical.rank("What does E450 mean?", ["E101 lidar.", "E450 lost localization."], 2)
    assert hits[0].index == 1
    assert hits[0].strong


def test_specific_phrase_is_strong_but_ubiquitous_phrase_is_not() -> None:
    texts = [f"Deep Learning Lab | page {i}" for i in range(6)]
    texts[2] += " | Course Outcomes: CO1 analyse neural networks."

    [hit] = lexical.rank("what are the course outcomes", texts, limit=1)
    assert hit.index == 2
    assert hit.strong
    assert not any(h.strong for h in lexical.rank("what is deep learning", texts, limit=6))


def test_no_overlap_returns_nothing() -> None:
    assert lexical.rank("capital of France", ["Program 1: word embeddings"], limit=5) == []
    assert lexical.rank("explain it", ["anything"], limit=5) == []


def test_word_forms_match() -> None:
    assert lexical.stem("models") == lexical.stem("model")
    assert lexical.stem("trained") == lexical.stem("train") == lexical.stem("training")
    assert lexical.stem("images") == lexical.stem("image")
    assert lexical.stem("classifies") == lexical.stem("classify")
    [hit] = lexical.rank("Which program uses pre-trained models?", ["Enable pre-train model"], 1)
    assert hit.coverage >= 0.5


def test_answer_instructions_are_not_search_terms() -> None:
    assert lexical.query_terms("Explain Program 4 step by step") == ["<unit>", "4"]
    assert lexical.query_terms("describe experiment 2 in detail") == ["<unit>", "2"]


def test_query_labels() -> None:
    assert lexical.query_labels("Explain Program 4 step by step") == {("<unit>", "4")}
    assert ("<unit>", "7") in lexical.query_labels("output of the seventh experiment")
    assert lexical.query_labels("what happens in week 3?") == {("week", "3")}
    assert lexical.query_labels("what is the batch size?") == set()


def test_label_needs_the_word_right_before_the_number() -> None:
    texts = [
        "Program 4: Build an autoencoder.",
        "Window size: the number of context words. In the program, it's 4.",
        "4 Write a program to classify reviews.",  # a row of a program list
    ]
    hits = lexical.rank("Explain Program 4 step by step", texts, limit=3)
    assert [h.index for h in hits if h.strong] == [0]


def test_context_counts_for_coverage_but_never_anchors() -> None:
    texts = ["Program 6: Forecast a time series.", "options = trainingOptions('adam');"]
    contexts = [None, "Program 6: Forecast a time series."]

    hits = lexical.rank("optimizer for time series forecasting", texts, 2, contexts=contexts)
    assert {h.index for h in hits} == {0, 1}
    [anchored] = [h for h in lexical.rank("program 6", texts, 2, contexts=contexts) if h.strong]
    assert anchored.index == 0
