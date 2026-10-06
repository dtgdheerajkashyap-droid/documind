# DocuMind

[![CI](https://github.com/dtgdheerajkashyap-droid/documind/actions/workflows/ci.yml/badge.svg)](https://github.com/dtgdheerajkashyap-droid/documind/actions/workflows/ci.yml)

**Ask questions about your PDFs and get answers grounded in, and cited from, your own documents.**

DocuMind is a full-stack retrieval-augmented generation (RAG) app. You upload PDFs; it extracts,
chunks, embeds, and indexes them. When you ask a question, it retrieves the most relevant passages
and has an LLM answer **using only those passages**, with clickable citations (filename, page, exact
passage). If the documents don't contain the answer, it says
**"I couldn't find this in your documents."** instead of guessing.

- **Backend:** Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Alembic · PostgreSQL
- **RAG:** PyMuPDF · `all-MiniLM-L6-v2` embeddings (local, ONNX Runtime) · ChromaDB · Google Gemini (swappable with Ollama)
- **Frontend:** Next.js 16 (App Router) · TypeScript · Tailwind CSS 4
- **Quality:** 92 pytest tests · 27 Vitest tests · ruff · black · ESLint · Prettier · GitHub Actions · Docker Compose

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
9. [Production hardening](#production-hardening)
10. [Deployment](#deployment)
11. [Design decisions & trade-offs](#design-decisions--trade-offs)
12. [Limitations](#limitations)
13. [Future improvements](#future-improvements)
14. [Project structure](#project-structure)

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
- **Private per-browser workspaces** (no sign-up): every visitor only sees their own documents,
  vectors, and chats. See [Production hardening](#production-hardening).
- **One-click sample documents**, so first-time visitors can try the app without a PDF.
- **Abuse protection:** streaming request-size cap, per-workspace document quota, duplicate
  detection by SHA-256, and rate limits on chat and uploads.
- **Self-healing index:** after a restart, interrupted uploads are re-queued and lost vectors are
  rebuilt from the chunk text stored in Postgres.
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
        BG["Ingestion queue<br/>(single worker thread)"]
    end

    PG[("PostgreSQL<br/>documents · chunks<br/>sessions · messages")]
    CH[("ChromaDB<br/>chunk vectors + metadata")]
    ST["ONNX Runtime<br/>all-MiniLM-L6-v2 (local)"]
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
| `providers` | Abstract `LLMProvider`, `EmbeddingProvider`, `VectorStore` with concrete Gemini/Ollama, ONNX/sentence-transformers, and Chroma implementations |
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
| `MAX_REQUEST_MB` | `60` | Hard cap on a whole upload request, enforced while it streams in |
| `MAX_FILES_PER_UPLOAD` | `10` | Files per upload request |
| `MAX_DOCUMENTS_PER_WORKSPACE` | `25` | Documents per workspace (per browser) |
| `EMBEDDING_BACKEND` | `onnx` | `onnx` (ONNX Runtime, no PyTorch) or `sentence-transformers` (`pip install sentence-transformers` first) |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | A sentence-transformers model; the `onnx` backend needs one that ships `onnx/model.onnx` |
| `EMBEDDING_DEVICE` | `cpu` | `cuda` if available (`sentence-transformers` backend only) |
| `EMBEDDING_BATCH_SIZE` | `32` | Encode batch size; smaller lowers peak RAM |
| `EMBEDDING_THREADS` | `0` | ONNX Runtime threads (`0` = one per core) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `150` | Characters; overlap must be < size |
| `RETRIEVAL_TOP_K` | `5` | Chunks sent to the LLM |
| `RETRIEVAL_MIN_SCORE` | `0.3` | Cosine similarity below which we refuse |
| `HISTORY_TURNS` | `3` | Previous turns used to rewrite follow-ups |
| `QUERY_REWRITE_ENABLED` | `true` | Toggle follow-up rewriting |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `CORS_ORIGIN_REGEX` | *(empty)* | Extra allowed origins as a regex (e.g. Vercel preview URLs) |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `20` | Per client IP; `0` disables |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` | `10` | Per client IP; `0` disables |
| `TRUSTED_PROXY_HOPS` | `0` | Reverse proxies whose `X-Forwarded-For` entries are trusted; `0` ignores the (forgeable) header |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | `console` for human-readable logs |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend → API URL (inlined at build time) |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | `20` | Client-side upload limit hint |

## API

Interactive docs are at `/docs` (Swagger) and `/redoc`.

Every endpoint accepts an optional **`X-Workspace-Id: <uuid>`** header. Documents and chat sessions
are scoped to that workspace, and IDs from another workspace return `404`. The frontend generates
one random UUID per browser. Requests without the header use a shared default workspace (handy
for curl and scripts).

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/documents` | Upload one or more PDFs (`multipart/form-data`, field `files`). Returns `201 {documents, rejected}`; ingestion runs in the background |
| `POST` | `/api/documents/samples` | Add the two bundled sample PDFs to the workspace |
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
`invalid_workspace` (400), `not_found` (404), `payload_too_large` (413), `rate_limited` (429 with
`Retry-After`), `llm_error` (502, sent as an SSE `error` event mid-stream), `llm_not_configured`
(503), and `internal_error` (500). Every response carries an `X-Request-ID` header that matches the
structured request log line.

## Testing & quality

```bash
# Backend (from backend/)
pytest                                        # 92 tests, SQLite + temporary Chroma, offline
TEST_DATABASE_URL=postgresql+psycopg://... pytest   # same suite against PostgreSQL
ruff check . ../scripts && black --config pyproject.toml --check . ../scripts

# Frontend (from frontend/)
npm test            # Vitest + Testing Library (27 tests)
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
| `test_workspaces_and_limits.py` | Workspace isolation (documents, chat retrieval, document filter, sessions), duplicate rejection, document quota, upload rate limit, request-size cap with and without `Content-Length`, sample documents, `X-Forwarded-For` trust, startup recovery, rebuilding a wiped vector index from Postgres |
| `test_config.py` | Settings validation, rate limiter |

Tests use a deterministic hashing "embedding" and a scripted fake LLM, so they need no network,
model download, or API key. The real Chroma store is used.

**CI** (`.github/workflows/ci.yml`): ruff + black → Alembic upgrade/downgrade/upgrade on a Postgres
16 service → pytest on SQLite (with coverage) and on Postgres; frontend lint, Prettier, typecheck,
Vitest, and production build; then `docker compose build` for both images.

## Evaluation

`scripts/evaluate.py` ingests the sample PDFs in [`backend/sample_docs`](backend/sample_docs)
(a fictional company handbook and robot manual) into a throwaway SQLite + Chroma store, runs the
labelled questions in [`scripts/eval/dataset.json`](scripts/eval/dataset.json), and writes
[`docs/evaluation_results.md`](docs/evaluation_results.md).

```bash
cd backend
.venv/Scripts/python ../scripts/evaluate.py            # Windows (macOS/Linux: .venv/bin/python)
.venv/Scripts/python ../scripts/evaluate.py --judge    # + end-to-end answers and LLM-as-judge (needs an API key)
.venv/Scripts/python ../scripts/evaluate.py --judge --judge-model gemini-3.1-flash-lite   # grade with a different model
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

**End-to-end with the LLM** (`--judge`, default chunks, answers by `gemini-flash-latest`):

| Metric | Self-judged (`gemini-flash-latest`) | Independent judge (`gemini-3.1-flash-lite`) |
|---|---|---|
| Mean LLM-judge score (1–5) | 4.89 (sixteen 5s, two 4s) | 4.83 (fifteen 5s, three 4s) |
| Unanswerable questions refused (threshold + grounding prompt) | 5/5 | 5/5 |
| Answerable questions wrongly refused | 0/18 | 0/18 |

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
- LLM judges tend to favour their own outputs, so the run was repeated with a different judge
  model: 4.83 vs 4.89, so self-preference had little effect here. Human labels would still be the
  gold standard. `docs/evaluation_results.md` holds the independent-judge run.
- The lowest-scoring answerable question scored 0.308, close to the 0.3 threshold. Raising the
  threshold would trade false refusals for fewer LLM calls.

## Production hardening

Before deploying publicly, the project was reviewed for what would break or be abused once
strangers could reach it. These were the findings and the fixes:

| Risk found in review | Fix | Verified by |
|---|---|---|
| Every visitor saw, searched, and could delete everyone's documents and chats | Anonymous **workspaces**: a random UUID per browser (`X-Workspace-Id`), stored on documents and sessions and in vector metadata; every query is filtered by it | `test_workspaces_and_limits.py`: isolation of lists, reads, deletes, chat retrieval, the document filter, and sessions |
| The 20 MB check ran only after FastAPI had spooled the whole multipart body to disk, so a multi-GB upload could fill it | `BodySizeLimitMiddleware` rejects from `Content-Length`, or by counting bytes as they stream in (chunked uploads), with `413` | Tests for both paths; no partial file left behind |
| The rate limiter trusted `X-Forwarded-For`, which any client can forge to get a fresh quota | Header used only with `TRUSTED_PROXY_HOPS`, and then only the entry appended by the trusted proxy | Unit tests with forged headers |
| Unlimited documents per user; the same file uploaded twice duplicated every citation | Per-workspace document quota, upload rate limit, SHA-256 duplicate detection | Quota, rate-limit, and duplicate tests |
| Free hosts wipe the disk on restart: documents stayed `ready` while their vectors vanished, and in-flight uploads stuck at `processing` forever | Postgres is the source of truth. On startup, interrupted uploads are re-queued (or marked failed with a clear message), and missing vectors are **rebuilt from chunk text in Postgres** | Recovery and re-index tests (vectors deleted, original PDF deleted, retrieval restored) |
| Parallel uploads each ran the embedding model in their own thread, competing for CPU and RAM | Single-worker ingestion queue | Upload tests wait on the queue |
| An empty first visit: recruiters rarely have a PDF at hand | "Try with sample documents" button (`POST /api/documents/samples`) | API test plus the UI |
| The LLM judge graded its own answers (self-preference bias) | `--judge-model` to grade with a different model | Evaluation section |

## Deployment

The live demo runs on free tiers:

| Part | Host | Why |
|---|---|---|
| Frontend (Next.js) | **Vercel** | Native Next.js hosting, global CDN |
| Backend (FastAPI + embedding model) | **Render** free web service (Docker) | Vercel's serverless functions can't run it: it needs a disk for Chroma, a background ingestion worker, and long-lived streaming responses |
| Database | **Neon** (serverless Postgres) | Free managed Postgres; keeps documents, chunks, and chats across backend restarts |

Render's free instance has 512 MB of RAM. PyTorch alone needs about 400 MB, so the embedding model
runs on **ONNX Runtime** instead (same `all-MiniLM-L6-v2` weights and pooling; vectors match the
sentence-transformers output to ~1e-7). With `EMBEDDING_BATCH_SIZE=8` the API peaks around 300 MB
while ingesting.

The instance's disk is ephemeral. That's fine because of the self-healing index: on restart the
backend rebuilds Chroma from the chunks stored in Neon. Free Render services sleep after 15 minutes
without traffic, and the first request then takes about a minute while the container wakes up (the
frontend explains this if the API is unreachable).

**Deploy it yourself:**

1. Create a Neon project, a Render API key, and a Vercel token, and put them in `deploy.env`
   (copy `deploy.env.example`; the real file is gitignored), with `GEMINI_API_KEY` in `.env`.
2. Backend: push to GitHub (Render builds `backend/Dockerfile` from the repository), then run
   `backend/.venv/Scripts/python scripts/deploy_render.py --frontend-url https://<your-app>.vercel.app --wait`.
   This creates the service (or updates its environment and redeploys). The container runs
   `alembic upgrade head` on start, and later pushes to `main` redeploy automatically.
3. Frontend: from `frontend/`, run
   `npx vercel deploy --prod --build-env NEXT_PUBLIC_API_URL=https://documind-api.onrender.com`.

`scripts/deploy_hf_space.py` deploys the same image to a Hugging Face Docker Space instead; those
now require a Hugging Face PRO subscription.

## Design decisions & trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| **Chunk per page** | Every citation maps to exactly one page | Sentences spanning a page break are split; short pages produce small chunks |
| **Character-based chunking** with boundary preference | Simple, deterministic, no tokenizer dependency; 800 chars ≈ 150–200 tokens, well within MiniLM's 256-token window | Not token-exact; semantic chunking could group ideas better |
| **Local embeddings (MiniLM)** | Free, private, no key, 384-d vectors are fast on CPU | Weaker than large API embedding models on hard queries |
| **Chroma (embedded, persistent)** | No extra service; metadata filtering for the document filter | Single-node; for scale use pgvector/Qdrant |
| **Postgres + Chroma, shared chunk UUID** | Relational data (status, sessions, history) in a real DB; vectors in a vector index | Two stores to keep consistent; handled with cleanup on failure/delete and an "is it still there?" check after ingestion |
| **In-process single-worker ingestion queue** + startup recovery | No extra infrastructure; one job at a time keeps CPU/RAM predictable on a small server; interrupted jobs are re-queued on start | Jobs live in memory: a restart re-queues them only if the uploaded file survived (otherwise the document is marked `failed` with "please re-upload"). A broker-backed queue (Celery/RQ/Arq) would make this fully durable |
| **Postgres as the source of truth, Chroma as a derived index** | Chunk text is stored in Postgres, so a wiped vector index is rebuilt on startup without the original PDFs | Re-embedding takes time proportional to corpus size |
| **Anonymous workspaces** instead of accounts | Privacy between visitors of a public demo with zero sign-up friction | Not authentication: the workspace UUID is a bearer secret kept in `localStorage`; clearing browser storage loses access |
| **Similarity threshold + prompt-level refusal** | Cheap early exit, plus LLM judgement for subtle cases | Threshold is corpus- and model-specific; calibrate with the eval script |
| **Citations filtered to `[n]` actually cited** | The panel shows what the answer relied on | If a model forgets markers, all retrieved sources are shown as a fallback |
| **SSE over `fetch`** (not WebSockets) | One-directional streaming fits; plain HTTP, proxy-friendly; POST body supported | Custom client-side parser (`lib/sse.ts`, unit tested) since `EventSource` is GET-only |
| **Pre-stream validation** | Missing key, unknown session, and rate limit return proper JSON status codes, not a broken stream | Errors after streaming starts arrive as an `error` event |
| **Provider interfaces + one composition root** | Swap Gemini ↔ Ollama with one env var; tests inject fakes | A small amount of indirection |
| **In-memory rate limiter** | Simple, dependency-free | Per process; use Redis with multiple replicas |
| **SQLite-compatible models** | Fast offline tests; the eval script needs no database server | CI also runs the full suite on Postgres to catch dialect differences |

**Assumptions / defaults chosen:**

- **No accounts:** isolation comes from anonymous per-browser workspaces (see Production
  hardening). Anyone with a workspace's UUID can access it.
- Default model `gemini-flash-latest` with `gemini-flash-lite-latest` as fallback. Transient
  Gemini errors (429/503) are retried with exponential backoff, and streaming only retries before
  the first token, so users never see duplicated text.
- Up to 10 files per upload request, 25 documents per workspace, 20 MB per file.
- "Document filter empty" means search all ready documents.
- History for rewriting is the last `HISTORY_TURNS` × 2 messages. The answer prompt uses the
  standalone query rather than the full chat transcript, which keeps prompts short and grounded.
- Scanned (image-only) PDFs are rejected with a clear "no extractable text" message rather than
  OCR'd.

## Limitations

- No OCR, so scanned PDFs fail ingestion. Tables and multi-column layouts are extracted as plain
  text and may lose structure.
- The ingestion queue is in memory: an upload interrupted by a restart can only be resumed if its
  file survived the restart.
- No real authentication or user accounts (workspaces are anonymous bearer IDs), and no automatic
  cleanup of abandoned workspaces yet.
- The rate limiter and embedding model live in the API process, so horizontal scaling needs Redis
  and a separate embedding worker.
- Retrieval is pure dense vector search: exact identifiers ("E450") rely on the embedding model
  rather than keyword matching.
- The evaluation set is small and synthetic.
- **Not verified locally:** `docker compose up` (Docker was unavailable on the build machine).
  Both Docker images are built in CI, and the backend image runs in production on Render.
- Free-tier Gemini capacity varies: during development every Flash model briefly returned 503
  "high demand", which is why the provider retries and falls back to a Lite model.

## Future improvements

- **Hybrid search** (BM25 + vectors with reciprocal rank fusion) and a **cross-encoder re-ranker**
- A durable job queue for ingestion, with retries and progress percentages
- OCR fallback (Tesseract) and table-aware parsing
- Real auth (OAuth/JWT) on top of workspaces, plus scheduled cleanup of inactive workspaces
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
│   ├── sample_docs/           # sample PDFs (UI "Try with sample documents" + evaluation)
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
│   ├── deploy_render.py       # deploys the backend to Render (free tier)
│   ├── deploy_hf_space.py     # alternative: Hugging Face Spaces (needs HF PRO)
│   └── eval/                  # dataset.json
├── deploy/huggingface/        # Space README (Docker SDK config)
├── docs/
│   ├── INTERVIEW_NOTES.md
│   └── evaluation_results*.md # generated by evaluate.py
├── docker-compose.yml
├── .env.example
└── .github/workflows/ci.yml
```
