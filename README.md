# DocuMind

[![CI](https://github.com/dtgdheerajkashyap-droid/documind/actions/workflows/ci.yml/badge.svg)](https://github.com/dtgdheerajkashyap-droid/documind/actions/workflows/ci.yml)

**Ask questions about your PDFs and get answers grounded in, and cited from, your own documents.**

DocuMind is a full-stack retrieval-augmented generation (RAG) app. You upload PDFs; it extracts,
chunks, embeds, and indexes them. When you ask a question, it retrieves the most relevant passages
and has an LLM answer **using only those passages**, with clickable citations (filename, page, exact
passage). If the documents don't contain the answer, it says
**"I couldn't find this in your documents."** instead of guessing.

- **Backend:** Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Alembic · PostgreSQL
- **RAG:** PyMuPDF · sentence-transformers `all-MiniLM-L6-v2` (local) · ChromaDB · Google Gemini (swappable with Ollama)
- **Frontend:** Next.js 16 (App Router) · TypeScript · Tailwind CSS 4
- **Quality:** 77 pytest tests · 23 Vitest tests · ruff · black · ESLint · Prettier · GitHub Actions · Docker Compose

---

## Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [How the RAG pipeline works](#how-the-rag-pipeline-works)
4. [Getting started](#getting-started)
5. [Configuration](#configuration)
6. [API](#api)
7. [Testing & quality](#testing--quality)
8. [Evaluation](#evaluation)
9. [Design decisions & trade-offs](#design-decisions--trade-offs)
10. [Limitations](#limitations)
11. [Future improvements](#future-improvements)
12. [Project structure](#project-structure)

---

## Features

- **Multi-file PDF upload** with drag-and-drop, client- and server-side validation (type, magic
  bytes, 20 MB limit), and live status: `queued → processing → ready | failed`.
- **Background ingestion:** per-page text extraction, cleaning, overlapping boundary-aware chunking,
  local embeddings, vectors in ChromaDB, chunk records in PostgreSQL.
- **Grounded chat** with **streamed answers (Server-Sent Events)** and inline `[n]` citations.
- **Two-layer hallucination guard:** a retrieval-similarity threshold that refuses *before* calling
  the LLM, and a strict grounding prompt with a fixed refusal phrase that is detected afterwards.
- **Chat sessions with history.** Follow-up questions ("what about opened bags?") are rewritten
  into standalone queries using recent turns before retrieval.
- **Citations panel:** click a citation to see the exact passage, filename, page, and relevance.
- **Document filter:** restrict a question to selected documents.
- **Documents page:** list, status, page and chunk counts, delete (removes DB rows, vectors, and the file).
- **Evaluation script** that reports hit-rate@k, MRR, refusal-gate accuracy, and an optional
  LLM-as-judge score, and writes a Markdown report.
- Dark/light theme, responsive layout, and loading, empty, and error states throughout.

## Architecture

```mermaid
flowchart LR
    subgraph Browser
        UI["Next.js app<br/>Chat · Documents"]
    end

    subgraph API["FastAPI backend"]
        R["api/routes<br/>documents · chat (SSE) · sessions · health"]
        S["services<br/>ingestion · retrieval · chat · prompts"]
        REPO["repositories"]
        P["providers (interfaces)<br/>LLM · Embeddings · VectorStore"]
        BG["BackgroundTasks<br/>ingestion worker"]
    end

    PG[("PostgreSQL<br/>documents · chunks<br/>sessions · messages")]
    CH[("ChromaDB<br/>chunk vectors + metadata")]
    ST["sentence-transformers<br/>all-MiniLM-L6-v2 (local)"]
    LLM["Gemini API<br/>(or Ollama)"]
    FS[("Uploaded PDFs<br/>on disk")]

    UI -- "REST + SSE" --> R
    R --> S
    R -. schedules .-> BG
    BG --> S
    S --> REPO --> PG
    S --> P
    P --> CH
    P --> ST
    P --> LLM
    R --> FS
```

The backend is layered so each concern can change independently:

| Layer | Responsibility |
|---|---|
| `api/routes` | HTTP only: parsing, validation, status codes, SSE framing |
| `services` | Business logic: ingestion pipeline, retrieval, chat orchestration, prompts |
| `repositories` | All SQL lives here (SQLAlchemy 2.0 typed queries) |
| `models` / `schemas` | ORM tables / Pydantic API contract |
| `providers` | Abstract `LLMProvider`, `EmbeddingProvider`, `VectorStore` with concrete Gemini/Ollama, sentence-transformers, and Chroma implementations |
| `core` | Settings (pydantic-settings), JSON logging, error handling, rate limiting, and the dependency container |

`core/container.py` is the single composition root. Tests build the same container with fakes
(a hashing embedder and a scripted LLM), so the whole API runs offline in a few seconds.

## How the RAG pipeline works

### Ingestion (runs in the background after upload)

```mermaid
flowchart LR
    A[PDF] --> B["Extract text per page<br/>(PyMuPDF blocks)"]
    B --> C["Clean<br/>NFKC, de-hyphenate,<br/>rebuild paragraphs"]
    C --> D["Chunk per page<br/>~800 chars, 150 overlap,<br/>split at ¶ › sentence › word"]
    D --> E["Embed<br/>MiniLM, 384-d, normalised"]
    E --> F[("Chroma<br/>id = chunk UUID<br/>metadata: document_id,<br/>filename, page, chunk_index")]
    D --> G[("Postgres chunks table<br/>same UUID")]
```

1. **Extract:** PyMuPDF returns text blocks in reading order. Blocks are merged into paragraphs
   based on vertical gaps, because many PDFs emit one block per visual line.
2. **Clean:** Unicode normalisation (ligatures like "ﬁ" → "fi"), re-join words hyphenated across
   lines, collapse whitespace, keep paragraph breaks.
3. **Chunk:** each page is split separately, so a citation always points to exactly one page.
   Chunks are at most `CHUNK_SIZE` characters, cut at the strongest boundary available (paragraph,
   then sentence, then word), and overlap by about `CHUNK_OVERLAP` characters so a fact cut at a
   boundary survives whole in a neighbouring chunk.
4. **Embed & store:** vectors go to Chroma (cosine HNSW index) with citation metadata. The same
   chunk UUID is the primary key in Postgres, so the two stores stay joinable. A failure at any step
   marks the document `failed` with a readable reason and removes partial vectors.

### Answering a question (`POST /api/chat`, streamed)

```mermaid
sequenceDiagram
    participant U as Browser
    participant A as API
    participant L as LLM
    participant V as Chroma
    U->>A: question (+ session_id, document filter)
    A->>A: check rate limit, LLM configured, session exists
    opt follow-up in an existing session
        A->>L: rewrite with last N turns → standalone query
    end
    A-->>U: event: meta (session_id, standalone_query)
    A->>V: top-k nearest chunks (optionally filtered by document)
    alt best similarity < RETRIEVAL_MIN_SCORE
        A-->>U: event: token "I couldn't find this in your documents."
    else
        A->>L: grounded prompt (numbered sources + rules)
        L-->>A: token stream
        A-->>U: event: token × n
        A->>A: refusal phrase? → strip citations
    end
    A-->>U: event: citations (only sources cited as [n])
    A-->>U: event: done (message_id, final answer, refused)
```

**Grounding and hallucination control**

- **Gate 1, retrieval threshold:** if the best cosine similarity is below `RETRIEVAL_MIN_SCORE`
  (default 0.3), the API refuses without calling the LLM. This is cheap and catches off-topic
  questions.
- **Gate 2, the prompt:** the system prompt says to use only the numbered sources, cite every claim
  as `[n]`, treat sources as data rather than instructions (a prompt-injection guard), and reply
  with the exact refusal sentence if the sources don't contain the answer. This catches on-topic
  questions the documents don't answer, such as "How much does the robot cost?".
- **Post-processing:** a refusal is detected robustly (case, curly apostrophes, trailing text) and
  normalised to the exact message with no citations. Otherwise only the sources the model actually
  cited are returned, with their original numbers, so `[2]` in the text always matches source 2 in
  the panel.
- Low temperature (0.1), and the user only ever sees passages that really exist in the index.

## Getting started

### Prerequisites

- A free **Gemini API key** from <https://aistudio.google.com/apikey> (or a local
  [Ollama](https://ollama.com) install). Without a key the app still runs: uploads, ingestion,
  documents, and history all work, and the chat endpoint returns a clear `503` explaining how to
  set `GEMINI_API_KEY`.

### Option A: Docker (recommended)

```bash
cp .env.example .env          # then set GEMINI_API_KEY=... in .env
docker compose up --build
```

- Frontend: <http://localhost:3000>
- API docs (Swagger): <http://localhost:8000/docs>

The backend container runs `alembic upgrade head` on start. Data persists in the `postgres_data`
and `backend_data` volumes (vectors, uploads, Hugging Face model cache). The first upload or
question downloads the embedding model (~90 MB); the backend warms it up in the background at
start-up.

### Option B: Local development

**1. PostgreSQL:** any Postgres 14+. The quickest way is to start only the database container:

```bash
docker compose up -d postgres
```

**2. Backend** (Python 3.11):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp ../.env.example .env            # set GEMINI_API_KEY; adjust DATABASE_URL if needed
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**3. Frontend** (Node 20+):

```bash
cd frontend
npm install
npm run dev                        # http://localhost:3000
```

The frontend reads `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

**Using Ollama instead of Gemini:** `ollama pull llama3.1:8b`, then set `LLM_PROVIDER=ollama` in
`.env`. No other change is needed.

> **Windows note:** on machines with Smart App Control / Application Control enabled, the compiled
> binaries of `psycopg[binary]` and `black` can be blocked ("An Application Control policy has
> blocked this file"). Workarounds: `pip install --no-binary black black` for black; for psycopg,
> set `PSYCOPG_IMPL=python` and put a `libpq.dll` folder (from any PostgreSQL install) on `PATH`.
> Docker and Linux/macOS are unaffected.

## Configuration

All settings are environment variables (read by `pydantic-settings`, optionally from `.env`). See
[`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` or `ollama`, the one switch for the LLM backend |
| `GEMINI_API_KEY` | *(empty)* | Required for chat with Gemini |
| `GEMINI_MODEL` | `gemini-flash-latest` | Any Gemini model id; the `-latest` alias survives Google retiring versions |
| `GEMINI_FALLBACK_MODELS` | `gemini-flash-lite-latest` | Comma-separated models tried in order when the primary is overloaded (503) or rate limited (429) |
| `GEMINI_THINKING_BUDGET` | *(empty)* | Optional thinking-token budget; empty = model default (newer models reject `0`) |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `llama3.1:8b` | Used when `LLM_PROVIDER=ollama` |
| `LLM_TEMPERATURE` | `0.1` | Low for factual answers |
| `LLM_MAX_OUTPUT_TOKENS` | `1024` | Answer length cap |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout |
| `DATABASE_URL` | `postgresql+psycopg://documind:documind@localhost:5432/documind` | SQLAlchemy URL |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Vector index location |
| `CHROMA_COLLECTION` | `documind_chunks` | Collection name |
| `UPLOAD_DIR` | `./data/uploads` | Stored PDFs |
| `MAX_UPLOAD_MB` | `20` | Per-file limit |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Any sentence-transformers model |
| `EMBEDDING_DEVICE` | `cpu` | `cuda` if available |
| `EMBEDDING_BATCH_SIZE` | `32` | Encode batch size |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `150` | Characters; overlap must be < size |
| `RETRIEVAL_TOP_K` | `5` | Chunks sent to the LLM |
| `RETRIEVAL_MIN_SCORE` | `0.3` | Cosine similarity below which we refuse |
| `HISTORY_TURNS` | `3` | Previous turns used to rewrite follow-ups |
| `QUERY_REWRITE_ENABLED` | `true` | Toggle follow-up rewriting |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `20` | Per client IP; `0` disables |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | `console` for human-readable logs |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend → API URL (inlined at build time) |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | `20` | Client-side upload limit hint |

## API

Interactive docs are at `/docs` (Swagger) and `/redoc`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/documents` | Upload one or more PDFs (`multipart/form-data`, field `files`). Returns `201 {documents, rejected}`; ingestion runs in the background |
| `GET` | `/api/documents` | List documents with status, page count, chunk count |
| `GET` | `/api/documents/{id}` | One document (poll this for status) |
| `DELETE` | `/api/documents/{id}` | Delete document, its chunks, vectors, and file → `204` |
| `POST` | `/api/chat` | Ask a question → `text/event-stream` (see below) |
| `GET` | `/api/sessions` | Chat sessions, most recent first, with message counts |
| `GET` | `/api/sessions/{id}` | Session with all messages and their citations |
| `DELETE` | `/api/sessions/{id}` | Delete a session → `204` |
| `GET` | `/api/health` | DB / vector store status, LLM provider, and whether it is configured |

**Chat request**

```json
{ "question": "How many PTO days do I get?", "session_id": null, "document_ids": null, "top_k": 5 }
```

**Chat SSE events**, in order:

```text
event: meta       data: {"session_id": "...", "standalone_query": "..."}
event: token      data: {"text": "Full-time employees receive 25 days"}   (repeated)
event: citations  data: {"citations": [{"index": 1, "filename": "...", "page": 3, "text": "...", "score": 0.47, ...}]}
event: done       data: {"message_id": "...", "session_id": "...", "answer": "...", "refused": false}
event: error      data: {"code": "llm_error", "message": "..."}            (instead of done, on failure)
```

**Errors** always use one JSON shape:

```json
{ "error": { "code": "llm_not_configured", "message": "GEMINI_API_KEY is not set. ...", "details": null } }
```

Codes include `validation_error` (422), `invalid_upload` (400, per-file reasons in `details`),
`not_found` (404), `rate_limited` (429 with `Retry-After`), `llm_not_configured` (503), and
`internal_error` (500). Every response carries an `X-Request-ID` header that matches the
structured request log line.

## Testing & quality

```bash
# Backend (from backend/)
pytest                                        # 77 tests, SQLite + temporary Chroma, offline
TEST_DATABASE_URL=postgresql+psycopg://... pytest   # same suite against PostgreSQL
ruff check . ../scripts && black --config pyproject.toml --check . ../scripts

# Frontend (from frontend/)
npm test            # Vitest + Testing Library (23 tests)
npm run lint        # ESLint (next/core-web-vitals + typescript)
npm run format:check && npm run typecheck && npm run build
```

**What the backend tests cover:**

| File | Covers |
|---|---|
| `test_chunking.py` | Size limits, overlap, sentence/paragraph boundaries, no mid-word starts, hard cuts, invalid params, page numbering, text cleaning |
| `test_ingestion.py` | Real PDF → pages → chunks → Chroma + Postgres; metadata correctness; scanned/blank PDFs and corrupt files marked `failed`; cleanup |
| `test_retrieval.py` | Ranking, top-k, document filter, low scores for unrelated queries, empty index |
| `test_grounding.py` | Threshold refusal **without calling the LLM**, LLM refusal normalisation, citation numbering, prompt contents, follow-up rewriting with history, rewrite fallback, mid-stream LLM errors |
| `test_api_*.py` | Upload validation (type, magic bytes, size, partial rejection), list/get/delete, SSE event sequence, session persistence, 404s, request validation, **missing `GEMINI_API_KEY` → 503 while the app still starts**, rate limiting, health, error format |
| `test_gemini_provider.py` | Retry on 429/503, fallback to the next model, fail fast on 400, no retry after streaming has started |
| `test_config.py` | Settings validation, rate limiter |

Tests use a deterministic hashing "embedding" and a scripted fake LLM, so they need no network,
model download, or API key. The real Chroma store is used.

**CI** (`.github/workflows/ci.yml`): ruff + black → Alembic upgrade/downgrade/upgrade on a Postgres
16 service → pytest on SQLite (with coverage) and on Postgres; frontend lint, Prettier, typecheck,
Vitest, and production build; then `docker compose build` for both images.

## Evaluation

`scripts/evaluate.py` ingests the sample PDFs in [`scripts/eval/sample_docs`](scripts/eval/sample_docs)
(a fictional company handbook and robot manual) into a throwaway SQLite + Chroma store, runs the
labelled questions in [`scripts/eval/dataset.json`](scripts/eval/dataset.json), and writes
[`docs/evaluation_results.md`](docs/evaluation_results.md).

```bash
cd backend
.venv/Scripts/python ../scripts/evaluate.py            # Windows (macOS/Linux: .venv/bin/python)
.venv/Scripts/python ../scripts/evaluate.py --judge    # + end-to-end answers and LLM-as-judge (needs an API key)
.venv/Scripts/python ../scripts/evaluate.py --chunk-size 200 --chunk-overlap 40 --output ../docs/evaluation_results_chunk200.md
```

- **hit-rate@k:** share of answerable questions with a correct (file, page) among the top k chunks
- **MRR:** mean of 1 / rank of the first correct chunk
- **Threshold gate:** how many unanswerable questions the similarity threshold alone refuses, and
  how many answerable ones it wrongly refuses
- **LLM-as-judge (`--judge`):** runs the real chat pipeline per question and grades answers 1–5
  against reference answers; also reports end-to-end refusal accuracy

### Results (actual script output)

Dataset: 2 PDFs, 9 pages, 18 answerable and 5 unanswerable questions. Embeddings:
`all-MiniLM-L6-v2`, top-k = 5, threshold = 0.3.

| Metric | Default chunks (800 / 150) → 9 chunks | Small chunks (200 / 40) → 49 chunks |
|---|---|---|
| Hit-rate@1 | 100.0% | 100.0% |
| Hit-rate@3 | 100.0% | 100.0% |
| Hit-rate@5 | 100.0% | 100.0% |
| MRR | 1.000 | 1.000 |
| Unanswerable refused by threshold alone | 3/5 | 3/5 |
| Answerable wrongly refused by threshold | 0/18 | 0/18 |

**End-to-end with the LLM** (`--judge`, default chunks, `gemini-flash-latest` answering and judging):

| Metric | Value |
|---|---|
| Mean LLM-judge score (1–5) | 4.89 (n = 18; sixteen 5s, two 4s) |
| Unanswerable questions refused (threshold + grounding prompt) | 5/5 |
| Answerable questions wrongly refused | 0/18 |

The full per-question tables are in [`docs/evaluation_results.md`](docs/evaluation_results.md) and
[`docs/evaluation_results_chunk200.md`](docs/evaluation_results_chunk200.md).

**Reading these numbers honestly:**

- The corpus is deliberately tiny so the script runs in seconds. Each page covers one topic, so
  page-level retrieval is easy, and 100% here **does not** predict performance on large, messy
  corpora. The value of the script is as a regression harness: swap in your own PDFs and
  questions.
- The threshold refuses off-topic questions (best scores 0.03–0.15) but **not** on-topic questions
  the documents can't answer: "Northwind's stock price" scored 0.56 and "Atlas-7 price" scored 0.68.
  That is exactly why the grounding prompt exists as a second gate, and the `--judge` run shows it
  working: the LLM refused both, bringing end-to-end refusals to 5/5.
- The judge is the same model that wrote the answers, so the 4.89 may be biased upward
  (self-preference). A stronger setup would use a different judge model or human labels.
- The lowest-scoring answerable question scored 0.308, close to the 0.3 threshold. Raising the
  threshold would trade false refusals for fewer LLM calls.

## Design decisions & trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| **Chunk per page** | Every citation maps to exactly one page | Sentences spanning a page break are split; short pages produce small chunks |
| **Character-based chunking** with boundary preference | Simple, deterministic, no tokenizer dependency; 800 chars ≈ 150–200 tokens, well within MiniLM's 256-token window | Not token-exact; semantic chunking could group ideas better |
| **Local embeddings (MiniLM)** | Free, private, no key, 384-d vectors are fast on CPU | Weaker than large API embedding models on hard queries |
| **Chroma (embedded, persistent)** | No extra service; metadata filtering for the document filter | Single-node; for scale use pgvector/Qdrant |
| **Postgres + Chroma, shared chunk UUID** | Relational data (status, sessions, history) in a real DB; vectors in a vector index | Two stores to keep consistent; handled with cleanup on failure/delete and an "is it still there?" check after ingestion |
| **FastAPI `BackgroundTasks`** for ingestion | Zero extra infrastructure; status tracked in the DB | Not durable: a restart mid-ingestion leaves a document `processing`. A queue (Celery/RQ/Arq) would fix that |
| **Similarity threshold + prompt-level refusal** | Cheap early exit, plus LLM judgement for subtle cases | Threshold is corpus- and model-specific; calibrate with the eval script |
| **Citations filtered to `[n]` actually cited** | The panel shows what the answer relied on | If a model forgets markers, all retrieved sources are shown as a fallback |
| **SSE over `fetch`** (not WebSockets) | One-directional streaming fits; plain HTTP, proxy-friendly; POST body supported | Custom client-side parser (`lib/sse.ts`, unit tested) since `EventSource` is GET-only |
| **Pre-stream validation** | Missing key, unknown session, and rate limit return proper JSON status codes, not a broken stream | Errors after streaming starts arrive as an `error` event |
| **Provider interfaces + one composition root** | Swap Gemini ↔ Ollama with one env var; tests inject fakes | A small amount of indirection |
| **In-memory rate limiter** | Simple, dependency-free | Per process; use Redis with multiple replicas |
| **SQLite-compatible models** | Fast offline tests; the eval script needs no database server | CI also runs the full suite on Postgres to catch dialect differences |

**Assumptions / defaults chosen:**

- **No authentication:** single-user, local-first app. All documents are searchable by everyone
  who can reach the API.
- Default model `gemini-flash-latest` with `gemini-flash-lite-latest` as fallback. Transient
  Gemini errors (429/503) are retried with exponential backoff, and streaming only retries before
  the first token, so users never see duplicated text.
- Up to 20 files per upload request.
- "Document filter empty" means search all ready documents.
- History for rewriting is the last `HISTORY_TURNS` × 2 messages. The answer prompt uses the
  standalone query rather than the full chat transcript, which keeps prompts short and grounded.
- Scanned (image-only) PDFs are rejected with a clear "no extractable text" message rather than
  OCR'd.

## Limitations

- No OCR, so scanned PDFs fail ingestion. Tables and multi-column layouts are extracted as plain
  text and may lose structure.
- Ingestion is in-process and not crash-safe (see `BackgroundTasks` above).
- No auth or multi-tenancy.
- The rate limiter and embedding model live in the API process, so horizontal scaling needs Redis
  and a separate embedding worker.
- Retrieval is pure dense vector search: exact identifiers ("E450") rely on the embedding model
  rather than keyword matching.
- The evaluation set is small and synthetic.
- **Not verified locally:** `docker compose up` (Docker was unavailable on the build machine).
  Both Docker images are built in CI instead.
- Free-tier Gemini capacity varies: during development every Flash model briefly returned 503
  "high demand", which is why the provider retries and falls back to a Lite model.

## Future improvements

- **Hybrid search** (BM25 + vectors with reciprocal rank fusion) and a **cross-encoder re-ranker**
- A durable job queue for ingestion, with retries and progress percentages
- OCR fallback (Tesseract) and table-aware parsing
- Auth (OAuth/JWT) and per-user document collections
- Highlighting the cited passage inside an embedded PDF viewer
- Larger, real-world eval set; track metrics in CI; answer-faithfulness metrics (e.g. RAGAS)
- Response caching for repeated questions; token and cost accounting
- pgvector to consolidate onto one database

## Project structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/routes/        # documents, chat (SSE), sessions, health
│   │   ├── core/              # config, logging, errors, rate limiting, container
│   │   ├── db/                # engine/session, declarative base
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── repositories/      # data access
│   │   ├── services/          # pdf_parser, chunking, ingestion, retrieval, prompts, chat_service
│   │   ├── providers/         # llm/ (gemini, ollama), embeddings/, vectorstore/ + factory
│   │   └── main.py            # app factory, middleware, CORS
│   ├── alembic/               # migrations
│   ├── tests/                 # pytest suite + fakes
│   └── Dockerfile
├── frontend/
│   ├── app/                   # routes: / (chat), /documents
│   ├── components/            # chat/, documents/, ui/, theme, header
│   ├── hooks/                 # useChat, useDocuments
│   ├── lib/                   # API client, SSE parser, types
│   ├── __tests__/             # Vitest component tests
│   └── Dockerfile
├── scripts/
│   ├── evaluate.py            # retrieval + LLM-judge evaluation
│   ├── make_sample_docs.py    # regenerates the sample PDFs
│   └── eval/                  # dataset.json, sample_docs/
├── docs/
│   ├── INTERVIEW_NOTES.md
│   └── evaluation_results*.md # generated by evaluate.py
├── docker-compose.yml
├── .env.example
└── .github/workflows/ci.yml
```
