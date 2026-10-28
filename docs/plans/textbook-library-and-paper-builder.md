# Plan: Textbook library, AI extraction agent, question bank and paper builder

Status: **implemented** (books: `docs/modules/books.md`; question bank and paper builder: `backend/app/modules/papers`). Written 2026-10-04 as the proposal; kept for its reasoning. Where the code and this plan differ, the code and the module docs win.

## 1. What we're building

1. **Teachers upload textbooks** as a PDF, or as photos of the pages. Each upload
   records the class, subject, title, publisher, edition and year.
2. **An agent processes the book** in the background:
   - it pulls the text from every page (the PDF's own text where it's usable, AI vision where it isn't);
   - it finds the chapters and where each one starts and ends;
   - it pulls out each chapter's exercise questions as structured rows;
   - it splits the chapter content into chunks for search (RAG).
3. **Teachers check the agent's work.** They confirm chapter boundaries and fix
   any bad text. Nothing the AI produces is treated as trusted until a person
   approves it.
4. **Teachers build papers** by picking a class and subject, the chapters, and
   question ranges ("Ch 1, Q1–Q10 as MCQs, Ch 2 Q3–Q7 as short questions").
   The system builds a draft paper.
5. **The teacher reviews the draft**: edit, swap, reorder, set marks, then approve.
   An approved paper goes into the **papers archive**, and its questions go into
   the **question bank** marked verified.
6. **Books stay after the school year ends.** Next year's teachers reuse the same
   book, chapters, questions and RAG index. A new edition is uploaded as a new book,
   and verified questions can be carried over to it.

## 2. Where it fits in the codebase

There are two new backend modules. They follow the existing pattern of
`models / repository / service / router / schemas`:

| Module | Owns |
| --- | --- |
| `app/modules/library` | books, files, pages, chapters, content chunks, processing jobs |
| `app/modules/papers` | question bank, question papers, paper sections and items |

The following are shared infrastructure that doesn't exist yet:

| New piece | Why |
| --- | --- |
| `app/common/storage/` | A book can be 50–300 MB. The inline data-URI approach used for logos won't work at that size. The interface has `put / get / delete / presigned_url`, with backends `local` (a Docker volume, for dev) and `s3` (MinIO/S3/R2, for prod). |
| `app/common/ai/` | A thin `AIClient` protocol with an `anthropic` backend and a `fake` backend for tests. This mirrors how `sms` and `whatsapp` switch between `console`, `null` and the real backend. |
| `processing_jobs` table + `python -m app.cli process-books` | A worker loop that claims jobs with `FOR UPDATE SKIP LOCKED`, the same outbox style as `send-whatsapp`. It runs as a new `book-worker` service in `compose.yml`. |

Every new table gets `TenantMixin + RequiredSchoolMixin` and an RLS policy through
`setup_tenant_table()`. Books are school-scoped and **never shared across tenants**,
because textbook content is copyrighted.

## 3. Data model

### library

```
books
  id, organization_id, school_id
  class_id → classes, subject_id → subjects
  title, publisher, edition, publication_year
  language            en | ur | bilingual
  status              uploaded → processing → needs_review → ready | failed | archived
  is_current          bool. One current book per (class, subject); the paper builder defaults to it
  page_count, sha256 (refuse duplicate uploads), uploaded_by, notes
  UNIQUE (school_id, class_id, subject_id, publisher, edition)

book_files            the original upload(s)
  id, book_id, kind (pdf | image), storage_key, mime, size_bytes, sha256, sort_order

book_pages            one row per physical page
  id, book_id, page_index (1..n), printed_label ("23", "vii")
  image_key           rendered PNG, used for preview and as vision input
  text                markdown. Math as LaTeX, tables as markdown, [FIGURE: …] placeholders
  method              text_layer | vision | manual
  status              pending | extracted | failed | edited
  edited_by, edited_at

chapters
  id, book_id, number, title, start_page_index, end_page_index
  status              proposed | verified
  verified_by, verified_at

content_chunks        RAG units, split by headings, about 500–800 tokens
  id, book_id, chapter_id, heading, page_from, page_to, content
  search tsvector     ('simple' config, so Urdu tokenises)
  embedding vector    nullable. Phase 6, needs pgvector

processing_jobs
  id, book_id, kind (render | extract_pages | detect_chapters | extract_questions | index)
  status (queued | running | done | failed), attempts, progress_done, progress_total,
  error, locked_at, input_tokens, output_tokens
```

### papers

```
questions             the question bank
  id, school_id, class_id, subject_id
  book_id, chapter_id  nullable. A teacher-written question may have no book
  source              book_exercise | ai_generated | teacher | past_paper
  exercise_label      "Exercise 1.2"
  number_label        "Q3 (ii)", as printed
  sequence            int, book order within the chapter. This is what "Q1–Q10" resolves against
  type                mcq | short | long | fill_blank | true_false | matching | numerical
  text, options jsonb, answer, default_marks, difficulty, language
  source_page_index, source_chunk_ids   (AI-generated questions cite their grounding)
  status              draft | verified | rejected
  content_hash        dedupe, and matching across editions
  created_by, verified_by, verified_at

question_papers
  id, school_id, class_id, subject_id, book_id, academic_year_id
  exam_paper_id       nullable → exam_papers. Ties the paper to a sitting in the existing exams module
  title, duration_minutes, total_marks, instructions
  spec jsonb          the teacher's original request, so the paper can be regenerated
  status              draft | approved | archived
  created_by, approved_by, approved_at

paper_sections        "Section A: MCQs, attempt all", "Section C: attempt any 3 of 5"
  id, paper_id, sort_order, title, instructions, question_type, marks_each,
  attempt_count nullable

paper_items
  id, section_id, question_id, sort_order, marks, text_override nullable
```

`text_override` lets a teacher reword a question just for one paper without
changing the bank copy.

## 4. The agent pipeline

Each step is a job. One failed page doesn't fail the whole book: the worker retries
it, and the page shows as `failed` in the review UI so the teacher can type it in
by hand.

**Step 1: Render and ingest.** The worker stores the original file. For each page
it renders a 150-dpi PNG with `pypdfium2`. Image uploads are normalised with Pillow
(orientation, max size) and become pages in upload order. It records `page_count`.

**Step 2: Extract page text.**
- If a PDF page has a good text layer, the worker uses it at no cost. "Good" means
  enough characters and real Unicode. Urdu PDFs exported from InPage often contain
  garbled glyph codes, so pages like that get sent to vision.
- Every other page goes to Claude vision with a strict transcription prompt. The
  output is markdown, math becomes LaTeX, figures become `[FIGURE: short description]`,
  and Urdu stays in Urdu script.
- The work runs through the **Message Batches API**. Nobody is waiting on the result,
  so batching costs about half as much and takes minutes, not seconds.

**Step 3: Detect chapters.**
1. Claude reads the first ~12 pages, finds the table of contents, and returns
   `[{number, title, printed_start_page}]` as structured output.
2. The worker works out the gap between printed page numbers and physical page
   indexes. It finds each chapter title in the page text, because front matter
   shifts the numbering.
3. If there's no table of contents, it scans the page text for chapter-heading patterns.

The chapters are saved as `proposed`. The book moves to **needs_review**, and the
teacher is notified.

**Step 4: Extract exercise questions.** For each chapter, Claude gets the chapter's
exercise pages and returns questions through a fixed tool schema (type, number
label, text, options, answer if the book prints one, page). The worker assigns
`sequence` in book order and saves the questions as `draft` with source `book_exercise`.

**Step 5: Index.** Chapter text is split into chunks on headings. The worker fills
in the `tsvector` now, and embeddings in phase 6. The book becomes **ready** once
a teacher has verified its chapters.

Rules for every AI call:
- Book text is untrusted input. It goes in as content, never as instructions, and
  results only come back through a JSON schema or tool schema, so a stray "ignore
  previous instructions" on a page can't do anything.
- Token counts are saved on the job. A per-organization monthly page allowance
  hooks into the existing billing entitlements, so one school can't run up an
  unlimited bill.

### Models (configurable)

| Task | Default | Why |
| --- | --- | --- |
| Page transcription (vision) | `claude-sonnet-5-5` | Handles Urdu script, math and tables well. Could drop to `claude-haiku-4-5-20251001` for clean English pages |
| TOC and question extraction, question generation | `claude-sonnet-5-5` | Structured reasoning over long text |
| Embeddings (phase 6) | Voyage (`voyage-3`-class) | Anthropic has no embedding model of its own; Voyage is the one it recommends |

## 5. Paper builder

### Request

```jsonc
{
  "class_id": "...", "subject_id": "...", "book_id": null,   // null = the class's current book
  "title": "First Term Test", "duration_minutes": 90,
  "sections": [
    { "title": "Section A: MCQs", "type": "mcq", "marks_each": 1,
      "picks": [ { "chapter": 1, "from": 1, "to": 10 } ] },
    { "title": "Section B: Short questions", "type": "short", "marks_each": 2,
      "attempt_count": 5,
      "picks": [ { "chapter": 1, "from": 1, "to": 4 }, { "chapter": 2, "from": 3, "to": 6 } ] },
    { "title": "Section C: Long questions", "type": "long", "marks_each": 5,
      "generate": { "chapters": [1, 2], "count": 3, "difficulty": "medium" } }
  ]
}
```

- **`picks`** select real book questions by chapter and number range. No AI is
  involved, so the result is deterministic and instant. If a number is missing
  (for example, the exercise only goes up to Q8), the builder warns instead of
  failing quietly.
- **`generate`** is where RAG comes in. The builder retrieves chunks from the chosen
  chapters and asks Claude for new questions grounded in them, each one citing its
  chunk. A second check discards any question whose answer isn't supported by the
  cited text. Generated questions are saved as `draft` with source `ai_generated`.
- The builder avoids reusing questions from the same class's papers in the last N months.

### Review and approval

The draft paper shows each question beside its source page image. The teacher can
edit the text, **swap** a question (with the next one in the range, another question
from the bank, or a newly generated one), reorder, and change marks.

Approving the paper does three things in one transaction:
- the paper becomes `approved`, and editing it after that requires a new version;
- every question used is promoted to `verified` in the bank;
- an `papers.approved` audit row is written.

### Output

The paper prints from an HTML page in Next.js using `@media print`, with the school
crest, class, subject, time and marks. It is **not** built with reportlab, because
reportlab can't shape Urdu or render LaTeX properly, and the browser does both.
The `diary-image.ts` feature took the same approach. An answer key prints as a
separate page.

## 6. Permissions

These follow the diary pattern: a permission says *what kind* of action someone
can take, and `ClassSubject.teacher_id` decides *which class and subject* they
can take it on.

| Code | Grants | Default |
| --- | --- | --- |
| `library:read` | view books, pages, chapters | teacher, principal |
| `library:upload` | upload books for subjects you teach; verify their chapters | teacher, principal |
| `library:manage` | any book: verify, archive, set current, re-run processing | principal |
| `papers:read` | view the bank and approved papers | teacher, principal |
| `papers:write` | build and approve papers for your own class and subject | teacher, principal |
| `papers:manage` | any paper, any class; reject bank questions | principal |

If a school wants a coordinator or principal to sign off on papers, that's a
`require_paper_approval` school setting. It can come later.

## 7. API (sketch)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/library/books` | multipart: metadata + PDF, or several images |
| GET | `/library/books?class_id=&subject_id=` | list with status and progress |
| GET/PATCH/DELETE | `/library/books/{id}` | metadata, `is_current`, archive |
| GET | `/library/books/{id}/pages?from=&to=` | text + signed image URLs |
| PUT | `/library/books/{id}/pages/{index}` | manual text fix |
| GET/PUT | `/library/books/{id}/chapters` | review and correct the boundaries; `POST …/chapters/verify` |
| POST | `/library/books/{id}/reprocess` | `{steps: [...]}` |
| GET | `/papers/questions?chapter_id=&type=&status=` | the bank |
| PATCH | `/papers/questions/{id}` | edit, verify, reject |
| POST | `/papers/drafts` | the builder request above → draft paper |
| GET/PUT | `/papers/{id}` | review and edit the draft |
| POST | `/papers/{id}/items/{item_id}/swap` | `{strategy: next \| bank \| generate}` |
| POST | `/papers/{id}/approve` | |
| GET | `/papers?class_id=&subject_id=&year=` | the archive |

## 8. Frontend

- `/library`: book grid by class and subject, an upload dialog (drag a PDF in, or
  pick several photos), and a live progress bar.
- `/library/[bookId]`: page viewer with the image on the left and editable text on
  the right, a chapter-boundary editor, and a "Verify chapters" button.
- `/question-bank`: filter by class, subject, chapter, type and status; bulk verify.
- `/papers/new`: section builder (chapter + from/to pickers, or "generate N").
- `/papers/[id]`: review screen with swap, edit and approve, plus print and answer-key views.

## 9. Config and dependencies

New settings: `AI_BACKEND (anthropic | fake)`, `ANTHROPIC_API_KEY`,
`AI_MODEL_TRANSCRIBE`, `AI_MODEL_REASON`, `STORAGE_BACKEND (local | s3)`,
`STORAGE_LOCAL_PATH`, `S3_ENDPOINT/BUCKET/KEY/SECRET`, `BOOK_MAX_UPLOAD_MB` (default 200),
`AI_MONTHLY_PAGE_ALLOWANCE`, and in phase 6 `EMBEDDINGS_BACKEND` and `VOYAGE_API_KEY`.

New packages: `anthropic`, `pypdfium2` and `pypdf`, `pillow`, `aioboto3` (s3 backend),
and `pgvector` in phase 6. **PyMuPDF is deliberately not used**: it's AGPL.

In compose: a `book-worker` service, an optional `minio` service, and in phase 6 the
db image switches to `pgvector/pgvector:pg16`.

## 10. Delivery phases

Each phase ships on its own and is usable by itself.

| # | Phase | Delivers | Test focus |
| --- | --- | --- | --- |
| 1 | Storage + library CRUD | upload, list, view the original file. No AI yet | upload limits, RLS isolation, duplicate sha |
| 2 | Worker + page extraction | render, text layer, vision fallback, page review UI | job claiming/retry, garbled-Urdu detection, fake AI client |
| 3 | Chapter detection + verification | TOC parse, page-offset mapping, boundary editor | offset mapping unit tests on fixture books |
| 4 | Question extraction + bank UI | exercise questions as drafts; edit, verify, reject | schema validation, sequence ordering |
| 5 | Paper builder + review + print | range picks, swap, approve → bank, print and answer key | range resolution, missing numbers, approve transaction, permission matrix |
| 6 | RAG generation | chunks + FTS, then pgvector embeddings, grounded "generate N" | grounding check rejects unsupported answers |
| 7 | Year-over-year | new edition upload, carry verified questions over by `content_hash`/similarity, usage metering | carry-over matching, allowance enforcement |

For a rough sense of size: phases 1–5 make a usable product without embeddings.
Phase 6 adds AI-written questions on top.

## 11. Decisions needed before implementation

1. **What does "question number from–to" mean?** This plan assumes it selects the
   book's own exercise questions by number. If it should instead mean "generate N
   new questions from this chapter", phase 6 moves ahead of phase 5.
2. **File storage.** S3-compatible storage (MinIO self-hosted, or Cloudflare R2/S3)
   is recommended, with local disk in dev. Does the production host have object
   storage?
3. **AI provider and cost.** Claude API calls cost money for each scanned page.
   PDFs with a usable text layer cost almost nothing to extract. Is a paid API key
   OK, and should usage be capped per plan?
4. **Book scope.** Per campus (`school_id`) is the default. Should books be shared
   across all campuses of one organization?
5. **Languages.** Are Urdu or bilingual books in scope from day one? That affects
   the vision prompts and the print layout.
6. **Approval.** Is the teacher's own approval enough, or must a principal or
   coordinator approve papers?
