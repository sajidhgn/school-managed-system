# Books module (textbook library)

Teachers add the textbooks a class is taught from and upload them **one chapter
at a time**: a chapter PDF, or photos of its pages in any order. An AI agent
then reads every page, puts the pages in printed-page order, checks the upload
really is the chapter it was filed under, and stores the text in PostgreSQL as
vectors (pgvector) so it can be searched by meaning.

## The teacher's flow

1. **Add a book**: Title, Class, Publisher, Version (and optionally a subject),
   plus the **chapter list** as printed on the contents page.
2. **Upload each chapter**: drop a PDF or the page photos on the chapter.
   Uploading queues the agent.
3. **Read the agent's report**: the chapter becomes **Ready**, or **Needs
   review** with the reasons. Teachers can open every page with its image and
   extracted text.
4. **Accept or fix**: upload the missing page, remove the stray one and run the
   agent again, or accept the chapter as it is.
5. **Search**: the book page has a semantic search box over every indexed
   chapter.

## The agent

`app/modules/books/pipeline.py` is the procedure. `agent.py` makes the model
calls, using three OpenAI APIs:

| Step | How | API / model |
| --- | --- | --- |
| Split | PDF pages rendered at 150 dpi (`pypdfium2`); photos made upright and capped at 2000 px (Pillow) | none |
| Read | a PDF page with a usable text layer is used as is (free). Every other page is transcribed to Markdown, with its printed page number | Responses API, vision, Structured Outputs: `BOOKS_READ_MODEL` (`gpt-5.4-mini`), through the Batch API by default |
| Order | sort by printed page number. An unnumbered page stays after its neighbour in the same PDF. An unnumbered loose photo is placed by asking "which page does this one follow?" | Decisions API: `BOOKS_DECISION_MODEL` (`gpt-6-luna`) |
| Verify | "which chapter of the list is this upload?", "which chapter is each page from?", "does this page open a chapter?". Also deterministic checks for missing or duplicate page numbers and unreadable pages | Decisions API |
| Index | ~600-token passages that remember their pages, embedded at 1536 dimensions into `book_chunks.embedding` (HNSW, cosine) | Embeddings API: `BOOKS_EMBEDDING_MODEL` (`text-embedding-3-small`), through the Batch API by default |

The Decisions API returns a probability for each option, so the report can say
"Chapter 2, 97%". Anything below 60%, an upload that matches a different
chapter, or a page from another chapter makes the chapter **Needs review**
instead of **Ready**. The chapter is still indexed either way.

Page text is untrusted input. It reaches the models only as evidence, and every
answer comes back through a schema or a fixed set of choices, so text on a page
cannot steer the agent.

## Batch API (half price)

Nobody waits on a chapter, so the two expensive-per-volume calls go through
OpenAI's Batch API, which costs half and answers within 24 hours (usually a few
hours). Each can be switched off on its own.

| Setting | What waits | While it waits |
| --- | --- | --- |
| `BOOKS_BATCH_READS=true` | Scanned and photographed pages (typeset PDF pages never need it) | The chapter is **Reading**: its files are locked, and the worker finishes the chapter once the batch is done |
| `BOOKS_BATCH_EMBEDDINGS=true` | The passages' vectors | The chapter is already **Ready** or **Needs review**, and its pages and report can be read. Only search skips it ("search index pending") until the worker writes the vectors |

- A request the batch did not answer (failed, expired) is done live when the
  batch is collected, so an expired batch costs money, never the chapter.
- A search query is always embedded live.
- The worker checks each waiting chapter's batches at most once a minute.
- Running the agent again on a chapter whose vectors are still pending replaces
  its passages; the old batch is cancelled and deleted at OpenAI, never
  collected.
- Deleting a chapter mid-batch leaves that batch to finish at OpenAI (a fraction
  of a cent) and its files to OpenAI's retention.
- The report records `batch_read_pages` / `batch_fallback_pages` and
  `batch_embedded_chunks` / `batch_embed_fallback_chunks`.

With both off, a chapter is read and indexed in minutes, at full price.

## Running it

Processing happens outside the request:

- `make process-books` (`python -m app.cli process-books`) drains the queue
  once. `make process-books watch=1` keeps polling. In Docker this runs as the
  `book-worker` service.
- Or set `BOOKS_INLINE_PROCESSING=true` and the API runs the chapter itself
  right after it is queued. This is convenient locally; in production use the
  worker so a deploy never kills a half-read chapter.
- With the Batch API on, **a worker must keep running** (`watch=1` or the
  `book-worker` service): it is what collects finished batches. Inline
  processing only starts a chapter.

Each chapter is claimed with `FOR UPDATE SKIP LOCKED` and its result is written
only if the claim still holds. Several workers can run at once, and a teacher
who deletes or re-uploads a chapter mid-run wins over the worker. A worker that
dies leaves the chapter `processing`; it is re-claimed after 30 minutes, at
most 3 times.

## Requirements

- **pgvector** on the PostgreSQL server. The migration runs
  `CREATE EXTENSION vector` and fails with install instructions if the
  extension is missing.
  - Ubuntu/Debian: `sudo apt install postgresql-18-pgvector`
  - Docker: `pgvector/pgvector:pg16` (used by both compose files)
- **`OPENAI_API_KEY`**. Without it, uploads work, but processing fails with a
  clear message and search returns 503.
- **Storage**: files and page images go under `BOOKS_STORAGE_PATH` (default
  `storage/books`, gitignored; `/data/books` volume in Docker).
  `app/common/storage.py` is local disk only. An S3 backend would be one more
  class with the same four methods.

## Rules

| | |
| --- | --- |
| `book:read` | see every book on the campus, its pages and files; search. Teacher and principal |
| `book:write` | add books; change the books **you** uploaded. Teacher and principal |
| `book:manage` | change or delete any book. Principal |

- File types are decided from the bytes (PDF, JPEG, PNG, WebP), never the
  filename.
- The same file cannot be uploaded to a chapter twice (sha256).
- Limits: `BOOKS_MAX_UPLOAD_MB` per file (50) and
  `BOOKS_MAX_PAGES_PER_CHAPTER` (150).
- Changing a chapter's files drops its pages and vectors immediately, so the
  index never mixes an old upload with a new one.
- A class cannot have the same title + publisher + version twice
  (case-insensitive). A new version is a new book.
- Every table has `organization_id` RLS and `school_id` campus scoping, like
  the rest of the system.

## Cost

A typeset PDF page costs one share of an embedding call and nothing else. A
photographed page costs one vision call (about 1.5–2k input tokens). On top of
that, each chapter needs a few Decisions calls and the embeddings. With the
Batch API on, the vision calls and the embeddings cost half; the vision calls
are almost all of the bill. A synthetic
three-page chapter (one PDF page, two photos) used about 6.6k input tokens in
total. Token counts are kept on each chapter (`input_tokens`, `output_tokens`)
and in its report.
