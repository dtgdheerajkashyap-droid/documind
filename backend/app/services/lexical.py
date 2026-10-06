"""Keyword (BM25) ranking, the lexical half of hybrid retrieval.

Dense embeddings capture meaning but are weak on labels and identifiers: a chunk that
starts with "Program 1:" and continues with 700 characters of code embeds as "code",
so "explain the first program" never finds it. This module ranks chunks by the query's
key terms instead, with a few normalisations for how people refer to numbered parts
of a document ("the first program" -> "program 1", "Experiment 01" -> "experiment 1")
and a light stemmer, so "pre-trained models" finds "pre-train model".
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise

_TOKEN = re.compile(r"[a-z0-9]+")

_ORDINALS = {
    "first": "1",
    "second": "2",
    "third": "3",
    "fourth": "4",
    "fifth": "5",
    "sixth": "6",
    "seventh": "7",
    "eighth": "8",
    "ninth": "9",
    "tenth": "10",
    "eleventh": "11",
    "twelfth": "12",
}
_NUMERIC_ORDINAL = re.compile(r"^(\d+)(st|nd|rd|th)$")

# Words people use for the numbered units of manuals, workbooks, and question papers.
# A query term from this group matches any member, so "first experiment" finds "Program 1".
_UNIT_WORDS = frozenset(
    {"program", "programs", "programme", "prog", "experiment", "experiments", "expt", "exp"}
    | {"exercise", "exercises", "practical", "practicals", "assignment", "assignments"}
)
_UNIT = "<unit>"

# Function words plus the instruction words of a question ("explain", "show me") that
# say what to do with the answer rather than what to look for.
_STOPWORD_LIST = """a an the of in on at to for from by with about into over under and or but not no
    is are was were be been being am do does did doing have has had having it its this that
    these those there here i me my we our you your he she they them their what which who whom
    whose when where why how can could should would will shall may might must please
    all every each any some
    explain explained describe tell show give list define summarize summarise elaborate
    discuss write mean means meaning detail details briefly brief number num
    """
_STOPWORDS = frozenset(_STOPWORD_LIST.split())
# How to answer, not what to look for: "explain Program 4 step by step" is about Program 4,
# not about the "Step 4" comments in every program's code.
_INSTRUCTION_PHRASES = re.compile(r"\b(step[\s-]+by[\s-]+step|in[\s-]+detail)\b")

K1 = 1.5
B = 0.75
# An anchor (label, code, or phrase) found in at most this many chunks is specific enough
# to pin results to: "Program 1" or "E450" is; "Atlas-7" in every chunk of the Atlas-7
# manual, or "deep learning" in every page header of a lab manual, is not.
MAX_ANCHOR_CHUNKS = 3
# Chunks sharing fewer of the query's key terms than this (and no anchor) are left out:
# one common word in common ("daily", "work") is noise that would outvote dense search.
MIN_COVERAGE = 0.5


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens, with numbers normalised ("01" -> "1", "1st" -> "1") and
    words stemmed ("trained" -> "train"). Stopwords are kept as they are."""
    tokens = []
    for token in _TOKEN.findall(text.lower()):
        if token.isdigit():
            token = str(int(token))
        elif match := _NUMERIC_ORDINAL.match(token):
            token = str(int(match.group(1)))
        elif token in _UNIT_WORDS:
            token = _UNIT
        elif token.isalpha() and token not in _STOPWORDS:
            token = stem(token)
        tokens.append(token)
    return tokens


def stem(word: str) -> str:
    """Strip common English endings so word forms match: models/model, trained/train,
    images/image, classifies/classify. Deliberately crude, and applied to both sides."""
    if len(word) < 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def query_terms(query: str) -> list[str]:
    """The key terms of a question, in order, without duplicates."""
    terms: list[str] = []
    for token in _TOKEN.findall(_INSTRUCTION_PHRASES.sub(" ", query.lower())):
        if token in _ORDINALS:
            token = _ORDINALS[token]
        if token in _STOPWORDS:
            continue
        for normalised in tokenize(token):
            if normalised not in terms:
                terms.append(normalised)
    return terms


def query_labels(query: str) -> set[tuple[str, str]]:
    """Numbered parts the question names: "explain Program 4" -> {("<unit>", "4")},
    "the third week" -> {("week", "3")}."""
    terms = query_terms(query)
    labels: set[tuple[str, str]] = set()
    for a, b in pairwise(terms):
        if a.isdigit() == b.isdigit():
            continue
        word, number = (b, a) if a.isdigit() else (a, b)
        if word.isalpha() or word == _UNIT:
            labels.add((word, number))
    return labels


@dataclass(frozen=True, slots=True)
class LexicalHit:
    index: int  # position in the scored corpus
    score: float  # BM25
    coverage: float  # fraction of the query's key terms found in the chunk
    anchored: bool  # the chunk names a numbered label or identifier from the query

    @property
    def strong(self) -> bool:
        """The chunk literally contains what the question points at ("Program 2", "E450").

        Strong enough to answer from even when the embedding similarity is low; other
        words of the question ("code", "aim") need not appear.
        """
        return self.anchored


def rank(
    query: str, texts: list[str], limit: int, contexts: list[str | None] | None = None
) -> list[LexicalHit]:
    """Rank `texts` against `query`: anchored matches first, then term coverage, then BM25.

    `contexts` (e.g. the title of the section a chunk belongs to) count towards term
    coverage and BM25 but never anchor a chunk: every chunk of "Program 4" would
    otherwise "name" Program 4.
    """
    terms = query_terms(query)
    if not terms or not texts:
        return []
    raw = [tokenize(text) for text in texts]
    docs = [
        tokenize(context) + tokens if context else tokens
        for tokens, context in zip(raw, contexts or [None] * len(texts), strict=True)
    ]
    avg_len = sum(len(d) for d in docs) / len(docs) or 1.0
    doc_freq = Counter(term for d in docs for term in set(d) if term in terms)

    scored: list[tuple[int, float, float, set[Anchor]]] = []
    for index, tokens in enumerate(docs):
        counts = Counter(tokens)
        present = [t for t in terms if counts[t]]
        if not present:
            continue
        score = 0.0
        for term in present:
            idf = math.log(1 + (len(docs) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            tf = counts[term]
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * len(tokens) / avg_len))
        own = set(raw[index])
        anchors = _anchors(raw[index], terms, [t for t in present if t in own])
        scored.append((index, score, len(present) / len(terms), anchors))

    anchor_freq = Counter(anchor for *_, anchors in scored for anchor in anchors)
    hits = [
        LexicalHit(
            index=index,
            score=score,
            coverage=coverage,
            anchored=any(anchor_freq[a] <= MAX_ANCHOR_CHUNKS for a in anchors),
        )
        for index, score, coverage, anchors in scored
    ]
    hits = [h for h in hits if h.anchored or h.coverage >= MIN_COVERAGE]
    hits.sort(key=lambda h: (h.anchored, h.coverage, h.score), reverse=True)
    return hits[:limit]


Anchor = tuple[str, ...]


def _anchors(tokens: list[str], terms: list[str], present: list[str]) -> set[Anchor]:
    """What in this chunk could pin it as *the* answer to the query.

    - an identifier from the query ("e450");
    - a query word directly followed by a query number, i.e. a label ("program 2",
      "week 3", "Program No. 2"), but not "...in the program, it's 4";
    - every key term, with two of them side by side: a phrase ("course outcomes").

    Nearness ignores stopwords, so "Vision of the Department" counts as a phrase.
    """
    anchors: set[Anchor] = {("id", t) for t in present if _is_identifier(t)}
    content = [t for t in tokens if t not in _STOPWORDS]
    wanted = set(present)
    anchors |= {
        ("label", word, number)
        for word, number in pairwise(content)
        if word in wanted and number in wanted and number.isdigit() and not word.isdigit()
    }
    # Numbers only pin a chunk as part of a label (above).
    pairs = _near_pairs(content, {t for t in wanted if not t.isdigit()})
    if len(present) == len(terms) > 1 and pairs:
        anchors.add(("phrase",))
    return anchors


def _is_identifier(term: str) -> bool:
    """Codes such as "e450" or "cs101": letters and digits in one token."""
    return any(c.isdigit() for c in term) and any(c.isalpha() for c in term)


def _near_pairs(tokens: list[str], terms: set[str]) -> set[tuple[str, str]]:
    """Pairs of different key terms that occur within one word of each other."""
    pairs: set[tuple[str, str]] = set()
    if len(terms) < 2:
        return pairs
    for i, token in enumerate(tokens):
        if token in terms:
            for other in tokens[i + 1 : i + 3]:
                if other in terms and other != token:
                    pairs.add((min(token, other), max(token, other)))
    return pairs
