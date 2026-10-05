# DocuMind: Interview Notes

Plain-language explanations of the core ideas behind this project, followed by likely interview
questions with concise answers. Numbers quoted here come from this repo's code and its
evaluation script output.

---

## Part 1: The concepts in plain language

### What RAG is, and why use it

A language model only knows what was in its training data, and it will confidently make things up
when it doesn't know. **Retrieval-augmented generation (RAG)** fixes this by looking up relevant
text first and handing it to the model with the question: *"Here are some passages. Answer using
only these."* The model becomes a reader and summariser of *your* documents rather than a source of
facts. It's like an open-book exam instead of answering from memory.

RAG beats fine-tuning for this use case because documents change constantly (upload, delete), you
need citations, and you need to control exactly what the model is allowed to know.

### Chunking

You can't send a whole 200-page PDF with every question: it's slow, expensive, and models get
worse at finding details in very long contexts. So documents are cut into **chunks** (passages).
Chunk size is a balance:

- **Too big:** each chunk mixes several topics, so its embedding becomes a blurry average, and you
  waste context on irrelevant text.
- **Too small:** a chunk lacks context ("It must be submitted within 30 days" — *what* must?).

DocuMind uses about **800 characters with 150 characters of overlap**. It splits at the strongest
natural boundary available (paragraph, then sentence, then word), and **never across pages**, so
every citation points to one page. **Overlap** means the end of one chunk repeats at the start of
the next: if a key sentence lands on a boundary, it still appears whole in one of the two.

Text is also **cleaned** first. PDFs are a layout format, not a text format, so extraction gives
line-broken words ("exam-\nple"), ligature characters ("ﬁ"), and sometimes one text block per
line. DocuMind rebuilds paragraphs from the vertical gaps between blocks.

### Embeddings

An **embedding** turns text into a list of numbers (here, 384 of them) such that texts with similar
*meaning* end up close together, even with different words. "How much vacation do I get?" lands
near "Full-time employees receive 25 days of paid time off", although the two share almost no
words. The model, `all-MiniLM-L6-v2`, is small, runs locally on CPU, and needs no API key.

Vectors are **L2-normalised** (length 1), so the dot product equals **cosine similarity**: 1 means
same direction (very similar), 0 means unrelated.

### Vector search

At question time, the question is embedded with the same model and the database finds the stored
chunk vectors closest to it: **nearest-neighbour search**. Comparing against every vector is exact
but slow at scale, so vector databases like **ChromaDB** use an approximate index called **HNSW**
(a layered graph you can "zoom in" through), which finds near-best matches in roughly logarithmic
time. DocuMind retrieves the **top 5** chunks and can filter by `document_id` metadata when the user
selects specific documents.

### Prompt grounding

The retrieved chunks are pasted into the prompt as **numbered sources**:

```text
SOURCES:
[1] (file: handbook.pdf, page 3)
Full-time employees receive 25 days of paid time off...

QUESTION: How many vacation days do I get?
```

The system prompt sets the rules: use only the sources, cite every claim as `[n]`, treat the
sources as data rather than instructions, and if the answer isn't there, reply with exactly
"I couldn't find this in your documents." Numbering lets the UI connect each `[n]` to the exact
passage, filename, and page.

### Reducing hallucinations (defence in depth)

No single trick removes hallucinations, so DocuMind layers several:

1. **Retrieval threshold:** if even the best chunk has low similarity (< 0.3), refuse *without
   calling the LLM*. Cheap, fast, and the model can't be tempted to answer from memory.
2. **Strict grounding prompt** with a fixed refusal sentence, and low temperature (0.1).
3. **Refusal detection:** if the model's output is the refusal (even with curly apostrophes or
   extra text), normalise it and show no citations.
4. **Citations the user can verify:** only passages that actually exist in the index are shown,
   and only the ones the answer cited.
5. **Follow-up rewriting:** "what about opened bags?" is rewritten to a full question before
   retrieval. Otherwise retrieval would fetch the wrong passages and the model would be tempted to
   improvise.
6. **Measurement:** the evaluation script checks retrieval (hit-rate, MRR) and refusal behaviour,
   and can grade answers with an LLM judge.

The evaluation shows why two gates are needed: the threshold refused off-topic questions like
"capital of Australia" (score 0.03) but not "What is the Atlas-7's price?" (score 0.68). That
question is on-topic, but the price isn't in the documents. Only the prompt-level gate can catch
that.

---

## Part 2: Likely interview questions

**1. Walk me through what happens when a user uploads a PDF.**
The API validates the file (extension, content type, `%PDF-` magic bytes, 20 MB limit) while
streaming it to disk, creates a `queued` row in Postgres, and returns `201` immediately. A
background task sets `processing`, extracts text per page with PyMuPDF, cleans it, chunks each
page, embeds the chunks in one batch, writes vectors with metadata to Chroma, and writes chunk rows
to Postgres with the same UUIDs. It then sets `ready` with page and chunk counts. Any failure sets
`failed` with a human-readable reason and removes partial vectors. The UI polls every 2 seconds
while anything is pending.

**2. Why both PostgreSQL and ChromaDB? Isn't that redundant?**
They do different jobs. Postgres holds relational, transactional data: document status, chat
sessions, message history, chunk text for auditing. Chroma is optimised for nearest-neighbour
search over vectors with metadata filters. The shared chunk UUID joins them. The trade-off is
keeping two stores consistent, handled with cleanup on failure and deletion. At larger scale I'd
consider pgvector to consolidate.

**3. How did you choose the chunk size and overlap?**
800 characters is about 150–200 tokens, well under MiniLM's 256-token input limit, so nothing is
truncated when embedding, and it's typically one or two paragraphs: one idea per chunk. The 150
overlap (~19%) protects facts cut at boundaries. Both are configurable, and the evaluation script
accepts `--chunk-size` so the choice can be tested; I ran 800/150 and 200/40 on the sample set.

**4. Why chunk per page instead of across the whole document?**
So every citation maps to exactly one page number, which makes citations precise and verifiable.
The cost is that a sentence spanning a page break gets split, and very short pages become small
chunks. For this product, precise citations were worth it.

**5. How does the system decide to say "I couldn't find this in your documents"?**
Two gates. First, if the top retrieval score is below `RETRIEVAL_MIN_SCORE` (0.3), it refuses
immediately without calling the LLM. Second, the prompt instructs the model to reply with that
exact sentence when the sources don't contain the answer; the backend detects this robustly and
strips citations. There are tests for both paths, including asserting that the LLM is *not*
called when the threshold refuses.

**6. How did you pick the 0.3 threshold, and what's the risk?**
From the score distribution on the evaluation set: off-topic questions scored 0.03–0.15, and
answerable ones scored 0.31–0.67. 0.3 sits between them with zero false refusals, but the lowest
answerable question (0.308) is close to the line. The threshold is model- and corpus-specific:
set it too high and you refuse valid questions; too low and you rely more on the LLM gate. It's
configurable and should be re-calibrated with the eval script on real data.

**7. How do follow-up questions work?**
For a question in an existing session, the backend sends the last few turns plus the new question
to the LLM with a "rewrite into a standalone question" prompt, and uses the result for retrieval
and answering. "How many days is that?" becomes "How many vacation days do full-time baristas
get?". If rewriting fails, it falls back to the original question. The rewritten query is stored
on the message and sent to the UI in the `meta` event for transparency.

**8. Why Server-Sent Events instead of WebSockets?**
Streaming here is one-way (server to client) and request-scoped, which is exactly what SSE is
for. It's plain HTTP, works through proxies, and needs no connection state on the server. Because
the endpoint is a POST (it needs a JSON body), the browser's `EventSource` (GET-only) can't be
used, so the frontend reads the `fetch` body stream and parses events with a small, unit-tested
parser.

**9. What happens if the Gemini API key is missing, or Gemini fails mid-answer?**
The app still starts. `/api/health` reports `llm_configured: false`, the UI shows a warning
banner, and `POST /api/chat` returns `503` with code `llm_not_configured` and a message telling
you to set `GEMINI_API_KEY`. This check runs *before* streaming starts so it's a proper HTTP
error. If the provider fails after streaming has begun, the server sends an `error` SSE event and
the UI shows it under the partial answer.

**10. How is the LLM swappable?**
All LLM access goes through an abstract `LLMProvider` with `generate`, `stream`, and
`ensure_configured`. `GeminiProvider` and `OllamaProvider` implement it, and a factory picks one
from `LLM_PROVIDER`. Embeddings and the vector store follow the same pattern. Services depend only
on the interfaces, which is also how tests inject a scripted fake LLM.

**11. How did you test something that depends on an LLM and a 90 MB model?**
With test doubles at the provider boundary. A deterministic hashing bag-of-words "embedder" keeps
retrieval meaningful (shared words lead to similar vectors) while running offline in milliseconds,
and a scripted fake LLM returns controlled answers, refusals, or errors. Chroma itself is real.
The 69 tests cover chunking, real-PDF ingestion, retrieval, grounding and refusal, and the API.
They run on SQLite locally and on Postgres in CI. The real model is exercised by the evaluation
script.

**12. How do you evaluate a RAG system?**
Separate retrieval from generation. For retrieval: **hit-rate@k** (was a correct source in the top
k?) and **MRR** (how high was the first correct source?), using labelled (file, page) pairs. For
refusal: include unanswerable questions and count correct refusals and false refusals. For
generation: LLM-as-judge comparing answers to reference answers on a 1–5 scale (the `--judge`
flag). On the small sample set retrieval was 100% at k=1, which mostly shows the set is easy, so I
treat the script as a regression harness, not a benchmark. The live `--judge` run scored 4.89/5
and refused 5/5 unanswerable questions, but since the judge is the same model that answered, I'd
use a different judge model for anything serious.

**Bonus: How do you handle an unreliable LLM API?**
Free-tier Gemini often returns 503 "high demand" or 429. The provider retries transient errors with
exponential backoff, then falls back to a configured list of models (Flash → Flash-Lite). Bad
requests (400) fail fast. For streaming, a retry is only safe before the first token reaches the
user, so the first chunk is read inside the retry loop. Model names use `-latest` aliases because
Google retires versions; `gemini-2.5-flash` disappeared for new keys during development.

**13. What are the main weaknesses, and how would you fix them?**
(a) Pure dense retrieval can miss exact identifiers: add hybrid BM25 + vector search and a
cross-encoder re-ranker. (b) `BackgroundTasks` isn't durable: move ingestion to a queue (Celery,
RQ, or Arq) with retries. (c) No OCR: add a Tesseract fallback. (d) The in-memory rate limiter is
per process: use Redis. (e) No auth: add users and per-user collections.

**14. How would you scale this to millions of chunks and many users?**
Run embedding and ingestion as separate worker services with a queue; move vectors to a scalable
store (pgvector with HNSW, Qdrant, or managed Pinecone) with tenant filtering; run stateless API
replicas behind a load balancer, with Redis for rate limiting and caching; batch embeddings, maybe
on a GPU; cache answers for repeated questions; and add observability (latency per stage,
retrieval scores, refusal rate, token usage).

**15. What did you do about security and robustness?**
Uploads are validated by extension, content type, and magic bytes, size-limited while streaming,
stored under generated UUID names (no user-controlled paths), and filenames are sanitised. Inputs
are validated with Pydantic (question length, UUIDs, top-k bounds). CORS is restricted to
configured origins, the chat endpoint is rate-limited per IP, secrets come only from environment
variables, and errors never leak stack traces. The prompt tells the model to treat document text
as data, not instructions, a basic prompt-injection defence. Structured JSON logs carry a request
ID for tracing.

---

### Bonus quick-fire answers

- **Why cosine similarity?** It measures direction, not length, so text length matters less, and
  with normalised vectors it's just a dot product.
- **Why temperature 0.1?** For factual QA you want deterministic, conservative wording, not
  creativity.
- **What is MRR of 1.0?** The first correct source was ranked #1 for every answerable question.
- **What does `top_k` trade off?** Higher k improves recall but adds noise and prompt length; 5 is
  a common middle ground for ~800-char chunks.
