"""Evaluate DocuMind's retrieval (and optionally answer quality) on a labelled dataset.

Retrieval metrics (no API key needed):
  * hit-rate@k  - share of answerable questions with a correct source in the top k
  * MRR         - mean reciprocal rank of the first correct source
  * refusal gate - how often the similarity threshold correctly refuses unanswerable
                   questions, and how often it wrongly refuses answerable ones

Optional LLM-as-judge (--judge, needs GEMINI_API_KEY or LLM_PROVIDER=ollama):
  runs the full chat pipeline for every question and asks the LLM to grade each
  answer against the reference answer on a 1-5 scale.

The script ingests the sample PDFs into a throwaway SQLite database and Chroma
index, so it needs neither Postgres nor a running server:

    cd backend && .venv/Scripts/python ../scripts/evaluate.py          # Windows
    cd backend && .venv/bin/python ../scripts/evaluate.py              # macOS/Linux
"""

# ruff: noqa: E402  (imports below need the sys.path tweak first)
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings
from app.core.container import AppContainer
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.workspace import DEFAULT_WORKSPACE_ID
from app.db.base import Base
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.models.document import DocumentStatus
from app.providers.factory import build_embeddings, build_llm, build_vector_store
from app.providers.llm.base import LLMProvider
from app.repositories.document_repository import DocumentRepository
from app.schemas.chat import ChatRequest

DEFAULT_DATASET = ROOT / "scripts" / "eval" / "dataset.json"
DEFAULT_DOCS = BACKEND / "sample_docs"  # also offered in the UI as sample documents
DEFAULT_OUTPUT = ROOT / "docs" / "evaluation_results.md"
WORKDIR = ROOT / "scripts" / "eval" / ".eval_workdir"

JUDGE_SYSTEM = (
    "You grade answers produced by a document question-answering system. "
    "Compare the CANDIDATE answer with the REFERENCE answer for the QUESTION. "
    "Score 5 if the candidate contains all key facts of the reference and nothing contradicting "
    "it; 4 if it is correct but misses a minor detail; 3 if partially correct; 2 if mostly wrong "
    "or a refusal; 1 if wrong. Ignore citation markers like [1]. "
    'Reply with JSON only: {"score": <1-5>, "reason": "<one sentence>"}'
)


@dataclass
class Result:
    id: str
    question: str
    expected: list[tuple[str, int]]
    retrieved: list[tuple[str, int, float]]
    first_hit_rank: int | None = None
    keyword_match: bool = False
    answer: str | None = None
    refused: bool | None = None
    judge_score: int | None = None
    judge_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def answerable(self) -> bool:
        return bool(self.expected)

    @property
    def best_score(self) -> float:
        return max((score for *_, score in self.retrieved), default=0.0)

    def gate_refuses(self, threshold: float) -> bool:
        """Mirrors the chat service: refuse unless a chunk is similar enough or a keyword match."""
        return self.best_score < threshold and not self.keyword_match


def build_settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {
        "database_url": f"sqlite:///{(WORKDIR / 'eval.db').as_posix()}",
        "chroma_persist_dir": WORKDIR / "chroma",
        "upload_dir": WORKDIR / "uploads",
        "log_format": "console",
        "log_level": "WARNING",
        "query_rewrite_enabled": False,
    }
    if args.top_k:
        overrides["retrieval_top_k"] = args.top_k
    if args.chunk_size:
        overrides["chunk_size"] = args.chunk_size
    if args.chunk_overlap is not None:
        overrides["chunk_overlap"] = args.chunk_overlap
    # Other values (chunking, threshold, LLM keys) come from env vars / backend/.env.
    return Settings(_env_file=BACKEND / ".env", **overrides)


def ingest(container: AppContainer, docs_dir: Path) -> dict[str, int]:
    pdfs = sorted(docs_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {docs_dir}")
    stats = {"documents": 0, "pages": 0, "chunks": 0}
    for pdf in pdfs:
        with session_scope(container.session_factory) as session:
            doc = DocumentRepository(session).create(
                workspace_id=DEFAULT_WORKSPACE_ID,
                filename=pdf.name,
                storage_path=str(pdf),
                file_size=pdf.stat().st_size,
            )
        container.ingestion.ingest(doc.id)
        with session_scope(container.session_factory) as session:
            doc = DocumentRepository(session).get(doc.id)
            if doc.status != DocumentStatus.READY:
                raise SystemExit(f"Ingestion failed for {pdf.name}: {doc.error_message}")
            stats["documents"] += 1
            stats["pages"] += doc.page_count or 0
            stats["chunks"] += doc.chunk_count
    return stats


def evaluate_retrieval(container: AppContainer, questions: list[dict], k: int) -> list[Result]:
    results = []
    for q in questions:
        expected = [(s["filename"], int(s["page"])) for s in q["expected_sources"]]
        chunks = container.retriever.retrieve(q["question"], top_k=k)
        result = Result(
            id=q["id"],
            question=q["question"],
            expected=expected,
            retrieved=[(c.filename, c.page, c.score) for c in chunks],
            keyword_match=any(c.keyword_match for c in chunks),
        )
        for rank, (filename, page, _) in enumerate(result.retrieved, 1):
            if (filename, page) in expected:
                result.first_hit_rank = rank
                break
                break
        result.extra["reference"] = q.get("reference_answer")
        results.append(result)
    return results


async def run_judge(
    container: AppContainer, judge: LLMProvider, results: list[Result], delay: float
) -> None:
    llm = judge
    service = container.chat_service
    for i, r in enumerate(results, 1):
        print(f"  [{i}/{len(results)}] {r.id}: answering...", flush=True)
        answer, refused = "", True
        async for event in service.stream(ChatRequest(question=r.question), DEFAULT_WORKSPACE_ID):
            if event.event == "done":
                answer, refused = event.data["answer"], event.data["refused"]
            elif event.event == "error":
                raise SystemExit(f"Chat pipeline failed on {r.id}: {event.data['message']}")
        r.answer, r.refused = answer, refused
        if delay:
            await asyncio.sleep(delay)

        if not r.answerable:
            continue
        prompt = f"QUESTION: {r.question}\nREFERENCE: {r.extra['reference']}\nCANDIDATE: {answer}\n"
        try:
            raw = await llm.generate(prompt, system=JUDGE_SYSTEM)
            match = re.search(r"\{.*\}", raw, re.S)
            verdict = json.loads(match.group(0)) if match else {}
            r.judge_score = int(verdict.get("score"))
            r.judge_reason = str(verdict.get("reason", ""))[:200]
        except (AppError, ValueError, TypeError) as exc:
            r.judge_reason = f"judge failed: {exc}"
        if delay:
            await asyncio.sleep(delay)


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def summarise(results: list[Result], k: int, threshold: float) -> dict[str, Any]:
    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]

    def hit_at(n: int) -> float:
        hits = [r for r in answerable if r.first_hit_rank is not None and r.first_hit_rank <= n]
        return len(hits) / len(answerable) if answerable else 0.0

    summary: dict[str, Any] = {
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "hit@1": hit_at(1),
        "hit@3": hit_at(min(3, k)),
        f"hit@{k}": hit_at(k),
        "mrr": (
            sum(1 / r.first_hit_rank for r in answerable if r.first_hit_rank) / len(answerable)
            if answerable
            else 0.0
        ),
        "gate_correct_refusals": sum(r.gate_refuses(threshold) for r in unanswerable),
        "gate_false_refusals": sum(r.gate_refuses(threshold) for r in answerable),
    }
    judged = [r for r in answerable if r.judge_score is not None]
    if judged:
        summary["judge_mean"] = sum(r.judge_score for r in judged) / len(judged)
        summary["judge_n"] = len(judged)
    if any(r.refused is not None for r in results):
        summary["e2e_correct_refusals"] = sum(bool(r.refused) for r in unanswerable)
        summary["e2e_false_refusals"] = sum(bool(r.refused) for r in answerable)
    return summary


def to_markdown(
    results: list[Result],
    summary: dict[str, Any],
    settings: Settings,
    stats: dict[str, int],
    k: int,
    llm_name: str | None,
) -> str:
    na, nu = summary["n_answerable"], summary["n_unanswerable"]
    lines = [
        "# DocuMind evaluation results",
        "",
        f"Generated by `scripts/evaluate.py` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.",
        "",
        "## Setup",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| Documents / pages / chunks | {stats['documents']} / {stats['pages']} / {stats['chunks']} |",
        f"| Questions | {na} answerable + {nu} unanswerable |",
        f"| Embedding model | `{settings.embedding_model}` |",
        f"| Chunk size / overlap | {settings.chunk_size} / {settings.chunk_overlap} chars |",
        f"| top-k | {k} |",
        f"| Refusal threshold (cosine) | {settings.retrieval_min_score} |",
        f"| LLM answering / judging | {llm_name or 'not run'} |",
        "",
        "## Retrieval metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Hit-rate@1 | {pct(summary['hit@1'])} |",
        f"| Hit-rate@3 | {pct(summary['hit@3'])} |",
        f"| Hit-rate@{k} | {pct(summary[f'hit@{k}'])} |",
        f"| MRR | {summary['mrr']:.3f} |",
        f"| Threshold gate: unanswerable correctly refused | {summary['gate_correct_refusals']}/{nu} |",
        f"| Threshold gate: answerable wrongly refused | {summary['gate_false_refusals']}/{na} |",
    ]
    if "judge_mean" in summary:
        lines += [
            "",
            "## End-to-end answer quality (LLM-as-judge)",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Mean judge score (1-5) | {summary['judge_mean']:.2f} (n={summary['judge_n']}) |",
            f"| Unanswerable correctly refused | {summary['e2e_correct_refusals']}/{nu} |",
            f"| Answerable wrongly refused | {summary['e2e_false_refusals']}/{na} |",
        ]
    lines += [
        "",
        "## Per-question results",
        "",
        "| ID | Question | Expected | First hit rank | Best score |"
        + (" Judge |" if "judge_mean" in summary else ""),
        "|---|---|---|---|---|" + ("---|" if "judge_mean" in summary else ""),
    ]
    for r in results:
        expected = ", ".join(f"{f} p.{p}" for f, p in r.expected) or "_(refuse)_"
        rank = (
            str(r.first_hit_rank) if r.first_hit_rank else ("n/a" if not r.answerable else "miss")
        )
        row = f"| {r.id} | {r.question} | {expected} | {rank} | {r.best_score:.3f} |"
        if "judge_mean" in summary:
            if r.answerable:
                row += f" {r.judge_score if r.judge_score is not None else 'n/a'} |"
            else:
                row += f" {'refused' if r.refused else 'answered'} |"
        lines.append(row)
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=None, help="default: RETRIEVAL_TOP_K (5)")
    parser.add_argument("--chunk-size", type=int, default=None, help="default: CHUNK_SIZE (800)")
    parser.add_argument(
        "--chunk-overlap", type=int, default=None, help="default: CHUNK_OVERLAP (150)"
    )
    parser.add_argument("--judge", action="store_true", help="also run LLM-as-judge (needs an LLM)")
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Gemini model for grading (default: same as answering). A different model "
        "avoids a model grading its own answers.",
    )
    parser.add_argument(
        "--delay", type=float, default=4.0, help="seconds between LLM calls (free-tier limits)"
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    configure_logging("WARNING", "console")
    settings = build_settings(args)
    k = settings.retrieval_top_k

    shutil.rmtree(WORKDIR, ignore_errors=True)
    WORKDIR.mkdir(parents=True)
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    container = AppContainer(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        embedder=build_embeddings(settings),
        vector_store=build_vector_store(settings),
        llm=build_llm(settings),
    )

    if args.judge:
        container.llm.ensure_configured()  # fail fast with a clear message

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    questions = dataset["questions"]

    print(f"Ingesting PDFs from {args.docs_dir} (first run downloads the embedding model)...")
    started = time.perf_counter()
    stats = ingest(container, args.docs_dir)
    print(
        f"  {stats['documents']} documents, {stats['pages']} pages, {stats['chunks']} chunks "
        f"in {time.perf_counter() - started:.1f}s"
    )

    print(f"Evaluating retrieval on {len(questions)} questions (k={k})...")
    results = evaluate_retrieval(container, questions, k)

    llm_name = None
    if args.judge:
        judge = container.llm
        if args.judge_model:
            judge = build_llm(settings.model_copy(update={"gemini_model": args.judge_model}))
        print(f"Running end-to-end answers ({container.llm.name}) + judge ({judge.name})...")
        asyncio.run(run_judge(container, judge, results, args.delay))
        llm_name = f"{container.llm.name} / {judge.name}"

    summary = summarise(results, k, settings.retrieval_min_score)
    markdown = to_markdown(results, summary, settings, stats, k, llm_name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print()
    print(markdown)
    print(f"Results written to {args.output}")
    engine.dispose()


if __name__ == "__main__":
    main()
