"""PostgreSQL + pgvector tests for the textbook library.

What a mocked suite would pass without:

  * THE WHOLE LOOP. A teacher's out-of-order photos go in through the API, the real
    worker (`process_pending`) claims the chapter as the restricted `sms_app` role,
    and the vectors it writes are found again by a `<=>` search.
  * OWNERSHIP. `book:write` changes only the books its holder uploaded;
    `book:manage` changes any.
  * ONE LIBRARY. A book is in the library once for the whole platform: another
    organization cannot upload it again, but adds the same copy to its own class
    and reads, searches and asks it from there -- without changing it. Until it
    is added, that organization sees neither the book, its pages nor its vectors.
    The uploader removing it leaves it for the schools that still use it.
  * FRESHNESS. Changing a chapter's files drops its old pages and vectors at once.
  * BATCH READING. A chapter waits in `reading` across worker passes, is locked
    against edits meanwhile, and finishes from the batch's readings.
  * BATCH EMBEDDING. A processed chapter is readable at once while its vectors
    wait for a batch; search picks it up when the batch is collected, and a
    re-run replaces (and deletes) a batch still pending.
  * ASK THE LIBRARY. Hybrid search ranks chunks across books by pgvector AND the
    generated tsvector; a chunk still waiting for its vector is found by its
    words; the answer is written from the retrieved passages only.
  * ADD A BOOK WITH AI. A book's cover and contents pages pre-fill the form; the
    class and subject offered are only those the caller may file under, nothing
    is stored, and the reading is valid as it stands for `POST /books`.

The model calls are the deterministic fake in `tests/books_fakes.py`; storage is a
temporary directory.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.common.email.sender import EmailMessage
from app.common.storage import LocalFileStorage
from app.core.config import Settings, get_settings
from app.modules.books.agent import AgentNotConfiguredError
from app.modules.books.jobs import process_pending
from app.modules.books.router import (
    get_agent_factory,
    get_book_storage,
    get_scan_reader_factory,
)
from tests.books_fakes import (
    ANSWERED,
    DISCARDED_BATCHES,
    FAKE_BATCHES,
    FRONT_MATTER_OFFERS,
    PHOTO_PAGES,
    SCAN_PROBLEM,
    FakeBatchAgent,
    FakeBookAgent,
    PhotoPage,
    make_pdf,
    make_photo,
)
from tests.integration.conftest import API, Tenant
from tests.integration.staff import _subject, _teacher
from tests.integration.test_academic_foundation import build_campus

pytestmark = pytest.mark.asyncio

BODY = (
    "Fractions describe parts of a whole. The numerator counts the parts we have, "
    "and the denominator counts the equal parts the whole is divided into."
)


class Actor:
    """Anyone signed in with a bearer token."""

    def __init__(self, client: AsyncClient, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = headers

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.client.get(url, headers=self.headers, **kw)

    async def post(self, url: str, **kw: Any) -> Any:
        return await self.client.post(url, headers=self.headers, **kw)

    async def patch(self, url: str, **kw: Any) -> Any:
        return await self.client.patch(url, headers=self.headers, **kw)

    async def delete(self, url: str, **kw: Any) -> Any:
        return await self.client.delete(url, headers=self.headers, **kw)


@dataclass
class Library:
    tenant: Tenant
    class_id: str
    head: Actor
    """Campus head: every school permission, so `book:manage`."""
    teacher: Actor
    """Seeded teacher role: `book:read` + `book:write`."""
    other_teacher: Actor
    storage: LocalFileStorage
    root: Path

    async def process(self) -> dict[str, int]:
        return await process_pending(limit=10, agent_factory=FakeBookAgent, storage=self.storage)


@pytest.fixture
async def library(tenant: Tenant, mailbox: list[EmailMessage], tmp_path: Path) -> Library:
    return await build_library(tenant, mailbox, tmp_path)


async def build_library(tenant: Tenant, mailbox: list[EmailMessage], tmp_path: Path) -> Library:
    """A campus with two teachers, a book store and the fake book agent wired in."""
    campus = await build_campus(tenant, mailbox)
    teacher = await _teacher(tenant, "books@test.example", "Book Teacher")
    other = await _teacher(tenant, "other@test.example", "Other Teacher")
    # Both are assigned to the class -- a teacher only sees the books of classes they
    # teach (see `teaching_scope`). The class teacher sees every book of the class;
    # the subject teacher sees the class-wide (subject-less) books the tests create.
    assigned = await campus.patch(
        f"{API}/classes/sections/{campus.section_id}",
        json={"class_teacher_id": teacher.user_id},
    )
    assert assigned.status_code == 200, assigned.text
    await _subject(campus, "ENG", teacher_id=other.user_id)

    root = tmp_path / "books"
    storage = LocalFileStorage(root)
    app = tenant.client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_book_storage] = lambda: storage
    app.dependency_overrides[get_agent_factory] = lambda: FakeBookAgent
    app.dependency_overrides[get_scan_reader_factory] = lambda: FakeBookAgent

    return Library(
        tenant=tenant,
        class_id=campus.class_id,
        head=Actor(tenant.client, campus.headers),
        teacher=Actor(tenant.client, teacher.headers),
        other_teacher=Actor(tenant.client, other.headers),
        storage=storage,
        root=root,
    )


async def create_book(actor: Actor, class_id: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "New Countdown 5",
        "class_id": class_id,
        "publisher": "Oxford",
        "version": "3rd Edition",
        "chapters": [
            {"number": 1, "title": "Numbers"},
            {"number": 2, "title": "Fractions"},
            {"number": 3, "title": "Decimals"},
        ],
        **overrides,
    }
    created = await actor.post(f"{API}/books", json=body)
    assert created.status_code == 201, created.text
    return dict(created.json())


def chapter(book: dict[str, Any], number: int) -> dict[str, Any]:
    return next(c for c in book["chapters"] if c["number"] == number)


def photos(pages: dict[int, tuple[int | None, str]]) -> list[tuple[str, tuple[str, bytes, str]]]:
    """Upload parts for photos keyed by fake-reader index."""
    parts = []
    for index, (printed, text) in pages.items():
        PHOTO_PAGES[index] = PhotoPage(printed, text)
        parts.append(("files", (f"IMG_{index}.jpg", make_photo(index), "image/jpeg")))
    return parts


async def upload(
    actor: Actor, book: dict[str, Any], number: int, parts: list[Any], *, process: bool = True
) -> Any:
    url = f"{API}/books/{book['id']}/chapters/{chapter(book, number)['id']}/files"
    return await actor.post(url, files=parts, data={"process": str(process).lower()})


# ---------------------------------------------------------------------------
# The whole loop
# ---------------------------------------------------------------------------


async def test_photos_in_any_order_are_ordered_verified_and_searchable(library: Library) -> None:
    book = await create_book(library.teacher, library.class_id)
    assert [c["status"] for c in book["chapters"]] == ["empty", "empty", "empty"]
    assert book["can_edit"] is True

    uploaded = await upload(
        library.teacher,
        book,
        2,
        photos(
            {
                101: (23, f"[CH 2] {BODY} Exercise 2.1"),
                102: (21, f"[CH 2] [OPENS] Chapter 2: Fractions. {BODY}"),
                103: (22, f"[CH 2] Equivalent fractions name the same amount. {BODY}"),
            }
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["status"] == "queued"
    assert [f["original_name"] for f in uploaded.json()["files"]] == [
        "IMG_101.jpg",
        "IMG_102.jpg",
        "IMG_103.jpg",
    ]

    assert await library.process() == {"ready": 1}
    assert await library.process() == {}  # nothing left to claim

    detail = (await library.teacher.get(f"{API}/books/{book['id']}")).json()
    processed = chapter(detail, 2)
    assert processed["status"] == "ready", processed["report"]
    assert processed["page_count"] == 3
    assert processed["report"]["matches_declared"] is True
    assert processed["report"]["detected_chapter_number"] == 2
    assert processed["report"]["vision_pages"] == 3
    assert detail["ready_chapter_count"] == 1

    pages = (
        await library.teacher.get(f"{API}/books/{book['id']}/chapters/{processed['id']}/pages")
    ).json()
    assert [p["printed_page_number"] for p in pages] == [21, 22, 23]
    assert [p["position"] for p in pages] == [1, 2, 3]
    assert pages[0]["opens_chapter"] is True
    assert {p["placement"] for p in pages} == {"printed_number"}

    image = await library.teacher.get(f"{API}/books/{book['id']}/pages/{pages[0]['id']}/image")
    assert image.status_code == 200, image.text
    assert image.headers["content-type"] == "image/jpeg"

    hits = await library.teacher.get(
        f"{API}/books/{book['id']}/search", params={"q": "equivalent fractions amount"}
    )
    assert hits.status_code == 200, hits.text
    assert hits.json(), "the chunk written by the worker should be found by pgvector"
    top = hits.json()[0]
    assert top["chapter_number"] == 2
    assert top["printed_start"] == 21 and top["printed_end"] == 23
    assert 0 < top["score"] <= 1

    # New files make the old index stale: it is dropped at once, not at the next run.
    more = await upload(
        library.teacher, book, 2, photos({104: (24, f"[CH 2] {BODY}")}), process=False
    )
    assert more.status_code == 200, more.text
    assert more.json()["status"] == "uploaded"
    assert more.json()["report"] is None
    stale = await library.teacher.get(f"{API}/books/{book['id']}/chapters/{processed['id']}/pages")
    assert stale.json() == []
    gone = await library.teacher.get(f"{API}/books/{book['id']}/search", params={"q": "fractions"})
    assert gone.json() == []

    requeued = await library.teacher.post(
        f"{API}/books/{book['id']}/chapters/{processed['id']}/process"
    )
    assert requeued.json()["status"] == "queued"
    assert await library.process() == {"ready": 1}


async def test_scanned_pages_wait_for_a_batch_and_finish_from_it(library: Library) -> None:
    FAKE_BATCHES.clear()
    DISCARDED_BATCHES.clear()

    async def batch_pass() -> dict[str, int]:
        return await process_pending(
            limit=10,
            agent_factory=FakeBatchAgent,
            storage=library.storage,
            force_batch_check=True,
        )

    book = await create_book(library.teacher, library.class_id)
    uploaded = await upload(
        library.teacher,
        book,
        2,
        photos(
            {
                201: (22, f"[CH 2] Equivalent fractions name the same amount. {BODY}"),
                202: (21, f"[CH 2] [OPENS] Chapter 2: Fractions. {BODY}"),
                203: (23, f"[CH 2] {BODY} Exercise 2.1"),
            }
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    chapter_id = uploaded.json()["id"]
    chapter_url = f"{API}/books/{book['id']}/chapters/{chapter_id}"

    assert await batch_pass() == {"reading": 1}
    (batch_id,) = FAKE_BATCHES
    detail = (await library.teacher.get(f"{API}/books/{book['id']}")).json()
    assert chapter(detail, 2)["status"] == "reading"

    # The batch is reading these exact files: changing them must wait.
    more = await upload(library.teacher, book, 2, photos({204: (24, f"[CH 2] {BODY}")}))
    assert more.status_code == 409, more.text
    assert (await library.teacher.post(f"{chapter_url}/process")).status_code == 409

    assert await batch_pass() == {}, "an unfinished batch leaves the chapter waiting"
    assert DISCARDED_BATCHES == []

    # One request went unanswered: its page is read live, the rest come from the batch.
    FAKE_BATCHES[batch_id].done = True
    del FAKE_BATCHES[batch_id].readings[next(iter(FAKE_BATCHES[batch_id].readings))]
    assert await batch_pass() == {"ready": 1}
    assert len(FAKE_BATCHES) == 2, "collecting submits no second READING batch"
    embed_batch = next(b for b in FAKE_BATCHES if b != batch_id)
    assert FAKE_BATCHES[embed_batch].vectors, "the chunks went to an embedding batch"
    assert list(DISCARDED_BATCHES) == [batch_id]

    detail = (await library.teacher.get(f"{API}/books/{book['id']}")).json()
    processed = chapter(detail, 2)
    assert processed["status"] == "ready", processed["report"]
    report = processed["report"]
    assert report["vision_pages"] == 3
    assert report["batch_read_pages"] == 2
    assert report["batch_fallback_pages"] == 1
    assert report["calls"]["read_batch"] == 2 and report["calls"]["read"] == 1

    pages = (await library.teacher.get(f"{chapter_url}/pages")).json()
    assert [p["printed_page_number"] for p in pages] == [21, 22, 23]

    FAKE_BATCHES[embed_batch].done = True
    assert await batch_pass() == {"indexed": 1}
    hits = await library.teacher.get(
        f"{API}/books/{book['id']}/search", params={"q": "equivalent fractions amount"}
    )
    assert hits.json() and hits.json()[0]["chapter_number"] == 2


async def test_vectors_wait_for_a_batch_while_the_chapter_is_already_readable(
    library: Library,
) -> None:
    FAKE_BATCHES.clear()
    DISCARDED_BATCHES.clear()

    async def batch_pass() -> dict[str, int]:
        return await process_pending(
            limit=10,
            agent_factory=FakeBatchAgent,
            storage=library.storage,
            force_batch_check=True,
        )

    book = await create_book(library.teacher, library.class_id)
    # Two long typeset pages: two chunks, and no page needs a reading batch.
    pdf = make_pdf(
        [
            (21, f"[CH 2] [OPENS] Chapter 2: Fractions. {BODY * 12}"),
            (22, f"[CH 2] Equivalent fractions name the same amount. {BODY * 12}"),
        ]
    )
    uploaded = await upload(
        library.teacher, book, 2, [("files", ("chapter-2.pdf", pdf, "application/pdf"))]
    )
    assert uploaded.status_code == 200, uploaded.text
    chapter_url = f"{API}/books/{book['id']}/chapters/{uploaded.json()['id']}"

    async def current() -> dict[str, Any]:
        return chapter((await library.teacher.get(f"{API}/books/{book['id']}")).json(), 2)

    async def search() -> list[dict[str, Any]]:
        found = await library.teacher.get(
            f"{API}/books/{book['id']}/search", params={"q": "equivalent fractions amount"}
        )
        assert found.status_code == 200, found.text
        return list(found.json())

    # Processed in one pass: pages and report are there, only search waits.
    assert await batch_pass() == {"ready": 1}
    (first,) = FAKE_BATCHES
    assert len(FAKE_BATCHES[first].vectors) == 2
    processed = await current()
    assert processed["status"] == "ready" and processed["indexing"] is True
    pages = (await library.teacher.get(f"{chapter_url}/pages")).json()
    assert [p["printed_page_number"] for p in pages] == [21, 22]
    assert await search() == [], "a chunk without its vector is not searchable yet"
    by_words = await library.teacher.get(
        f"{API}/books/search", params={"q": "equivalent fractions", "book_id": book["id"]}
    )
    assert by_words.status_code == 200, by_words.text
    assert by_words.json(), "library search finds a chunk by its words before its vector"
    assert {h["matched_by"] for h in by_words.json()} == {"keywords"}
    assert await batch_pass() == {}, "an unfinished batch leaves the chunks waiting"

    # One chunk went unanswered: it is embedded live, the other comes from the batch.
    FAKE_BATCHES[first].done = True
    del FAKE_BATCHES[first].vectors[next(iter(FAKE_BATCHES[first].vectors))]
    assert await batch_pass() == {"indexed": 1}
    assert list(DISCARDED_BATCHES) == [first]
    indexed = await current()
    assert indexed["indexing"] is False
    report = indexed["report"]
    assert report["batch_embedded_chunks"] == 1
    assert report["batch_embed_fallback_chunks"] == 1
    assert report["calls"]["embed_batch"] == 1 and report["calls"]["embed"] == 1
    hits = await search()
    assert len(hits) == 2 and hits[0]["printed_start"] == 22
    assert await batch_pass() == {}, "nothing left to collect"

    # Re-run twice before the batch finishes: the first pending batch is replaced
    # and deleted, never collected into chunks that no longer exist.
    for _ in range(2):
        assert (await library.teacher.post(f"{chapter_url}/process")).status_code == 200
        assert await batch_pass() == {"ready": 1}
    second, third = (b for b in FAKE_BATCHES if b != first)
    assert list(DISCARDED_BATCHES) == [first, second]
    assert await search() == [], "the re-run's chunks wait for their own batch"

    FAKE_BATCHES[second].done = True
    assert await batch_pass() == {}, "a replaced batch is never collected"
    FAKE_BATCHES[third].done = True
    assert await batch_pass() == {"indexed": 1}
    assert len(await search()) == 2
    assert (await current())["indexing"] is False


NEWTON = (
    "Newton's second law of motion says that the force on a body equals its mass "
    "multiplied by its acceleration, written F = ma. A larger force gives a larger "
    "acceleration."
)


async def test_ask_the_library_answers_from_every_book_with_citations(library: Library) -> None:
    ANSWERED.clear()
    maths = await create_book(library.teacher, library.class_id)
    science = await create_book(
        library.teacher,
        library.class_id,
        title="Science Explorer 5",
        publisher="Collins",
        chapters=[{"number": 1, "title": "Forces"}],
    )
    await upload(library.teacher, maths, 2, photos({161: (21, f"[CH 2] [OPENS] {BODY}")}))
    await upload(library.teacher, science, 1, photos({162: (40, f"[CH 1] [OPENS] {NEWTON}")}))
    assert await library.process() == {"ready": 2}

    found = await library.teacher.get(f"{API}/books/search", params={"q": "newton second law"})
    assert found.status_code == 200, found.text
    top = found.json()[0]
    assert top["book_title"] == "Science Explorer 5" and top["chapter_title"] == "Forces"
    assert top["printed_start"] == 40
    assert top["matched_by"] == "both", "the exact words and the meaning both point here"
    assert top["score"] == 1.0, "first in both rankings"

    asked = await library.teacher.post(
        f"{API}/books/ask", json={"question": "  What is Newton's   second law? "}
    )
    assert asked.status_code == 200, asked.text
    answer = asked.json()
    assert answer["found"] is True
    assert answer["cited"] == [1]
    assert answer["sources"][0]["book_title"] == "Science Explorer 5"
    assert answer["answer"].endswith("[1]")
    question, passages = ANSWERED[-1]
    assert question == "What is Newton's second law?"
    assert passages[0].source == "Science Explorer 5, Ch 1: Forces, p. 40"
    assert passages[0].number == 1

    # Narrowed to one book, the other book's passages never reach the model.
    narrowed = await library.teacher.post(
        f"{API}/books/ask", json={"question": "What is Newton's law?", "book_id": maths["id"]}
    )
    assert {s["book_id"] for s in narrowed.json()["sources"]} <= {maths["id"]}
    assert all("Science" not in p.source for p in ANSWERED[-1][1])

    uncovered = await library.teacher.post(
        f"{API}/books/ask", json={"question": "[UNCOVERED] fractions of a pizza"}
    )
    assert uncovered.json()["found"] is False
    assert uncovered.json()["answer"] == "Not in these books."
    assert uncovered.json()["cited"] == []


async def test_an_upload_filed_under_the_wrong_chapter_needs_review(library: Library) -> None:
    book = await create_book(library.teacher, library.class_id)
    await upload(
        library.teacher,
        book,
        1,
        photos({111: (40, f"[CH 3] [OPENS] Chapter 3: Decimals. {BODY}")}),
    )
    assert await library.process() == {"needs_review": 1}

    detail = (await library.teacher.get(f"{API}/books/{book['id']}")).json()
    flagged = chapter(detail, 1)
    assert flagged["status"] == "needs_review"
    assert flagged["report"]["detected_chapter_number"] == 3
    codes = {i["code"] for i in flagged["report"]["issues"]}
    assert {"chapter_mismatch", "foreign_pages"} <= codes
    # Still indexed: the review is about trust, not about whether the text exists.
    assert flagged["report"]["chunks"] == 1

    accepted = await library.teacher.post(
        f"{API}/books/{book['id']}/chapters/{flagged['id']}/accept"
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ready"
    assert accepted.json()["report"]["accepted_by_name"] == "Book Teacher"

    again = await library.teacher.post(f"{API}/books/{book['id']}/chapters/{flagged['id']}/accept")
    assert again.status_code == 409
    assert again.json()["code"] == "NOT_IN_REVIEW"


async def test_inline_processing_runs_for_a_principal_acting_on_a_campus(
    library: Library, db_settings: Settings
) -> None:
    """THE REGRESSION: the org-level principal's token carries no school, so the run
    must take its campus from the chapter row -- and must read it BEFORE the early
    commit, which discards the RLS binding for the rest of the request. Reading it
    after made a successful upload answer 404 and never start the agent."""
    inline = db_settings.model_copy(update={"BOOKS_INLINE_PROCESSING": True})
    app = library.tenant.client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_settings] = lambda: inline

    library.tenant.active_school_id = library.tenant.school_id
    principal = Actor(library.tenant.client, library.tenant.headers())
    book = await create_book(principal, library.class_id)

    uploaded = await upload(principal, book, 2, photos({151: (7, f"[CH 2] [OPENS] {BODY}")}))
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["status"] == "queued"  # the response is built before the run

    # The run happened after the response, inside the same ASGI call.
    detail = (await principal.get(f"{API}/books/{book['id']}")).json()
    assert chapter(detail, 2)["status"] == "ready", chapter(detail, 2)
    assert await library.process() == {}  # nothing left for the worker


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


async def test_write_covers_your_own_books_and_manage_covers_every_book(library: Library) -> None:
    book = await create_book(library.teacher, library.class_id)

    listed = await library.other_teacher.get(f"{API}/books")
    assert listed.status_code == 200, listed.text
    assert [(b["id"], b["can_edit"]) for b in listed.json()["items"]] == [(book["id"], False)]

    refused = await upload(library.other_teacher, book, 1, photos({121: (1, BODY)}))
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "BOOK_NOT_OWNED"
    renamed = await library.other_teacher.patch(
        f"{API}/books/{book['id']}", json={"title": "Mine now"}
    )
    assert renamed.status_code == 403

    added = await library.head.post(
        f"{API}/books/{book['id']}/chapters", json={"number": 4, "title": "Measurement"}
    )
    assert added.status_code == 201, added.text
    assert added.json()["status"] == "empty"

    assert (await upload(library.teacher, book, 1, photos({122: (1, BODY)}))).status_code == 200
    book_dir = library.root / library.tenant.organization_id
    assert any(book_dir.rglob("*.jpg"))

    deleted = await library.head.delete(f"{API}/books/{book['id']}")
    assert deleted.status_code == 204, deleted.text
    assert (await library.teacher.get(f"{API}/books/{book['id']}")).status_code == 404
    assert not any(book_dir.rglob("*.jpg")), "the book's files should be removed with it"


async def test_uploads_are_checked_by_content_and_never_duplicated(library: Library) -> None:
    book = await create_book(library.teacher, library.class_id)

    not_a_page = await upload(
        library.teacher, book, 1, [("files", ("notes.jpg", b"just some text", "image/jpeg"))]
    )
    assert not_a_page.status_code == 422, not_a_page.text
    assert not_a_page.json()["code"] == "UNSUPPORTED_FILE"

    twice_in_one = await upload(
        library.teacher, book, 1, photos({131: (1, BODY)}) + photos({131: (1, BODY)})
    )
    assert twice_in_one.status_code == 409
    assert twice_in_one.json()["code"] == "DUPLICATE_FILE"

    assert (await upload(library.teacher, book, 1, photos({132: (1, BODY)}))).status_code == 200
    again = await upload(library.teacher, book, 1, photos({132: (1, BODY)}))
    assert again.status_code == 409
    assert again.json()["code"] == "DUPLICATE_FILE"

    empty = chapter(book, 2)
    nothing = await library.teacher.post(f"{API}/books/{book['id']}/chapters/{empty['id']}/process")
    assert nothing.status_code == 422
    assert nothing.json()["code"] == "NO_FILES"

    clash = await library.teacher.post(
        f"{API}/books/{book['id']}/chapters", json={"number": 2, "title": "Again"}
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "DUPLICATE_CHAPTER_NUMBER"


async def test_the_same_book_cannot_be_added_to_a_class_twice(library: Library) -> None:
    created = await create_book(library.teacher, library.class_id)
    again = await library.teacher.post(
        f"{API}/books",
        json={
            "title": "new countdown - 5.",
            "class_id": library.class_id,
            "publisher": " OXFORD ",
            "version": "3rd edition",
        },
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "DUPLICATE_BOOK"
    assert again.json()["meta"] == {"book_id": created["id"], "on_shelf": True}

    # A new version is a new book.
    newer = await create_book(library.teacher, library.class_id, version="4th Edition")
    assert newer["version"] == "4th Edition"


async def test_a_book_is_in_the_library_once_and_every_school_reads_that_copy(
    library: Library, make_tenant: Callable[..., Any], mailbox: list[EmailMessage]
) -> None:
    book = await create_book(library.teacher, library.class_id)
    await upload(library.teacher, book, 2, photos({141: (5, f"[CH 2] {BODY}")}))
    assert await library.process() == {"ready": 1}
    assert book["grade"] == "Grade 9" and book["from_library"] is False

    rival: Tenant = await make_tenant(
        name="Rival Trust", email="rival@test.example", school_code="RIVAL"
    )
    campus = await build_campus(rival, mailbox, email="rival-head@test.example", students=0)
    head = Actor(rival.client, campus.headers)
    # The same grade under another name: their "Class IX" is the uploader's "Grade 9".
    named = await head.post(f"{API}/classes", json={"name": "Class IX", "level": 10})
    assert named.status_code == 201, named.text
    class_ix = named.json()["id"]

    # Until the campus adds it, the book is none of its business.
    assert (await head.get(f"{API}/books")).json()["items"] == []
    assert (await head.get(f"{API}/books/{book['id']}")).status_code == 404
    searched = await head.get(f"{API}/books/{book['id']}/search", params={"q": "fractions"})
    assert searched.status_code == 404
    assert (await head.get(f"{API}/books/search", params={"q": "fractions"})).json() == []
    ANSWERED.clear()
    asked = await head.post(f"{API}/books/ask", json={"question": "What are fractions?"})
    assert asked.json()["found"] is False
    assert ANSWERED == [], "with nothing retrieved, the answer model is never called"

    # ... but it is in the library, found by the campus's own name for the grade.
    found = await head.get(f"{API}/books/library", params={"q": "countdown", "grade": "Class IX"})
    assert found.status_code == 200, found.text
    [listed] = found.json()["items"]
    assert listed["id"] == book["id"]
    assert (listed["grade"], listed["on_shelf"], listed["school_count"]) == ("Grade 9", False, 1)
    assert listed["ready_chapter_count"] == 1
    other = await head.get(f"{API}/books/library", params={"grade": "Class 10"})
    assert other.json()["items"] == []

    # Uploading it again is refused, naming the copy to add instead.
    again = await head.post(
        f"{API}/books",
        json={
            "title": "NEW COUNTDOWN-5",
            "class_id": class_ix,
            "publisher": "oxford",
            "version": "3rd edition.",
        },
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "DUPLICATE_BOOK"
    assert again.json()["meta"] == {"book_id": book["id"], "on_shelf": False}

    added = await head.post(f"{API}/books/library/{book['id']}", json={"class_id": class_ix})
    assert added.status_code == 201, added.text
    ours = added.json()
    assert (ours["class_name"], ours["grade"]) == ("Class IX", "Grade 9")
    assert (ours["from_library"], ours["can_edit"], ours["can_remove"]) == (True, False, True)
    assert ours["school_count"] == 2 and ours["created_by_name"] is None
    assert [c["id"] for c in ours["chapters"]] == [c["id"] for c in book["chapters"]]
    twice = await head.post(f"{API}/books/library/{book['id']}", json={"class_id": campus.class_id})
    assert twice.status_code == 409 and twice.json()["code"] == "ALREADY_ON_SHELF"
    listed_again = await head.get(f"{API}/books/library", params={"q": "countdown"})
    assert listed_again.json()["items"][0]["on_shelf"] is True

    # It reads, searches and answers from the uploader's pages: read once, for both.
    pages = await head.get(f"{API}/books/{book['id']}/chapters/{chapter(book, 2)['id']}/pages")
    assert pages.status_code == 200, pages.text
    assert BODY in pages.json()[0]["text"]
    hits = await head.get(f"{API}/books/search", params={"q": "numerator denominator"})
    assert [h["book_id"] for h in hits.json()] == [book["id"]]
    answered = await head.post(f"{API}/books/ask", json={"question": "What are fractions?"})
    assert answered.json()["found"] is True

    # Only the uploader changes the book; the campus changes only where it files it.
    refused = await upload(head, ours, 1, photos({142: (1, BODY)}))
    assert refused.status_code == 403 and refused.json()["code"] == "BOOK_NOT_OWNED"
    renamed = await head.patch(f"{API}/books/{book['id']}", json={"title": "Ours now"})
    assert renamed.status_code == 403 and renamed.json()["code"] == "BOOK_NOT_OWNED"
    refiled = await head.patch(
        f"{API}/books/{book['id']}",
        json={"title": book["title"], "class_id": campus.class_id},
    )
    assert refiled.status_code == 200, refiled.text
    assert refiled.json()["class_id"] == campus.class_id
    uploader = (await library.teacher.get(f"{API}/books/{book['id']}")).json()
    assert uploader["class_id"] == library.class_id, "each campus files the book itself"

    # The uploader removing it leaves it -- files and all -- for the school using it.
    assert (await library.head.delete(f"{API}/books/{book['id']}")).status_code == 204
    assert (await library.teacher.get(f"{API}/books/{book['id']}")).status_code == 404
    kept = await head.get(f"{API}/books/{book['id']}")
    assert kept.status_code == 200 and kept.json()["school_count"] == 1
    assert any((library.root / library.tenant.organization_id).rglob("*.jpg"))

    # Added back, it is the uploader's to change again.
    back = await library.head.post(
        f"{API}/books/library/{book['id']}", json={"class_id": library.class_id}
    )
    assert back.status_code == 201, back.text
    assert (back.json()["from_library"], back.json()["can_edit"]) == (False, True)

    # The other school removing it takes it off its own books only.
    assert (await head.delete(f"{API}/books/{book['id']}")).status_code == 204
    assert (await head.get(f"{API}/books")).json()["items"] == []
    assert (await library.teacher.get(f"{API}/books/{book['id']}")).status_code == 200


# ---------------------------------------------------------------------------
# Add a book with AI
# ---------------------------------------------------------------------------


async def scan(actor: Actor, parts: list[Any]) -> Any:
    return await actor.post(f"{API}/books/scan", files=parts)


async def curriculum_ids(library: Library) -> dict[str, str]:
    listed = await library.head.get(f"{API}/classes/{library.class_id}/subjects")
    assert listed.status_code == 200, listed.text
    return {row["subject_name"]: row["subject_id"] for row in listed.json()}


async def test_a_books_cover_and_contents_fill_in_the_add_a_book_form(library: Library) -> None:
    cover = (
        None,
        "TITLE: Beginner  Mathematics\nPUBLISHER: Oxford University Press\n"
        "VERSION: 2nd Edition, 2026\nCLASS: Grade 9\nSUBJECT: Subject ENG",
    )
    # The second part of the book restarts its numbering, so the list is renumbered.
    contents = (3, "CH 1: Numbers\nCH 2: Shapes\nCH 1: Telling the time")
    FRONT_MATTER_OFFERS.clear()

    read = await scan(library.teacher, photos({151: cover, 152: contents}))

    assert read.status_code == 200, read.text
    body = read.json()
    assert body == {
        "title": "Beginner Mathematics",
        "publisher": "Oxford University Press",
        "version": "2nd Edition, 2026",
        "class_id": library.class_id,
        "class_printed": "Grade 9",
        "subject_id": (await curriculum_ids(library))["Subject ENG"],
        "subject_printed": "Subject ENG",
        "chapters": [
            {"number": 1, "title": "Numbers"},
            {"number": 2, "title": "Shapes"},
            {"number": 3, "title": "Telling the time"},
        ],
        "pages_read": 2,
        "notes": [],
    }
    assert FRONT_MATTER_OFFERS == [(["Grade 9"], ["Subject ENG"])]
    assert not library.root.exists() or not any(library.root.rglob("*")), "nothing is stored"

    # The reading is a valid book as it stands.
    created = await library.teacher.post(
        f"{API}/books",
        json={
            key: body[key]
            for key in ("title", "publisher", "version", "class_id", "subject_id", "chapters")
        },
    )
    assert created.status_code == 201, created.text
    assert [c["title"] for c in created.json()["chapters"]] == [
        "Numbers",
        "Shapes",
        "Telling the time",
    ]


async def test_a_reading_suggests_only_where_the_caller_may_file_the_book(
    library: Library,
) -> None:
    subject = await library.head.post(f"{API}/subjects", json={"code": "MTH", "name": "Maths"})
    assert subject.status_code == 201, subject.text
    linked = await library.head.post(
        f"{API}/classes/{library.class_id}/subjects", json={"subject_id": subject.json()["id"]}
    )
    assert linked.status_code == 201, linked.text
    cover = (None, "TITLE: New Countdown 9\nCLASS: Grade 9\nSUBJECT: Maths")

    # The campus head may file it under any subject of the class.
    by_head = await scan(library.head, photos({161: cover}))
    assert by_head.status_code == 200, by_head.text
    assert by_head.json()["subject_id"] == subject.json()["id"]

    # The English teacher is offered only English: the subject stays as printed.
    FRONT_MATTER_OFFERS.clear()
    by_teacher = await scan(library.other_teacher, photos({161: cover}))
    assert by_teacher.status_code == 200, by_teacher.text
    assert FRONT_MATTER_OFFERS == [(["Grade 9"], ["Subject ENG"])]
    assert by_teacher.json()["class_id"] == library.class_id
    assert by_teacher.json()["subject_id"] is None
    assert by_teacher.json()["subject_printed"] == "Maths"

    # A class the campus does not have is left for the teacher to choose.
    elsewhere = await scan(library.head, photos({162: (None, "TITLE: Science 7\nCLASS: Grade 7")}))
    assert elsewhere.status_code == 200, elsewhere.text
    assert elsewhere.json()["class_id"] is None
    assert elsewhere.json()["class_printed"] == "Grade 7"


async def test_a_whole_book_pdf_is_read_only_up_to_its_first_pages(library: Library) -> None:
    filler = f"{BODY} {BODY}"
    pages: list[tuple[int | None, str]] = [(None, f"TITLE: Big Book of Science\n{filler}")]
    pages += [(n, f"CH {n}: Topic {n}\n{filler}") for n in range(2, 21)]
    pdf = make_pdf(pages)

    read = await scan(library.teacher, [("files", ("book.pdf", pdf, "application/pdf"))])

    assert read.status_code == 200, read.text
    body = read.json()
    assert body["title"] == "Big Book of Science"
    assert body["pages_read"] == 16
    assert [c["number"] for c in body["chapters"]] == list(range(2, 17))
    assert body["notes"] and "first 16 pages" in body["notes"][0]


async def test_pages_that_show_no_book_are_refused(library: Library) -> None:
    blank = await scan(library.teacher, photos({171: (None, "A photo of a desk.")}))
    assert blank.status_code == 422, blank.text
    assert blank.json()["code"] == "NOTHING_READ"

    not_a_page = await scan(
        library.teacher, [("files", ("cover.jpg", b"just some text", "image/jpeg"))]
    )
    assert not_a_page.status_code == 422, not_a_page.text
    assert not_a_page.json()["code"] == "UNSUPPORTED_FILE"


async def test_the_dialog_learns_before_any_upload_whether_ai_reading_will_work(
    library: Library,
) -> None:
    ready = await library.teacher.get(f"{API}/books/scan/status")
    assert ready.status_code == 200, ready.text
    assert ready.json()["ready"] is True
    assert ready.json()["problem"] is None

    SCAN_PROBLEM[0] = "kie.ai rejected the API key."
    try:
        broken = await library.teacher.get(f"{API}/books/scan/status")
        assert broken.json()["ready"] is False
        assert broken.json()["problem"] == "kie.ai rejected the API key."

        # Nothing is sent to a provider that will refuse it.
        FRONT_MATTER_OFFERS.clear()
        refused = await scan(library.teacher, photos({181: (None, "TITLE: Science 9")}))
        assert refused.status_code == 503, refused.text
        assert refused.json()["code"] == "AI_NOT_READY"
        assert FRONT_MATTER_OFFERS == []
    finally:
        SCAN_PROBLEM[0] = None

    # A provider whose key is missing from .env says which setting to fill in.
    def unconfigured() -> Any:
        raise AgentNotConfiguredError(
            "OpenRouter is chosen (BOOKS_SCAN_PROVIDER=openrouter) but OPENROUTER_API_KEY "
            "is not set in backend/.env."
        )

    app = library.tenant.client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_scan_reader_factory] = lambda: unconfigured
    missing = (await library.teacher.get(f"{API}/books/scan/status")).json()
    assert missing["ready"] is False
    assert "OPENROUTER_API_KEY" in missing["problem"]


async def test_list_is_searched_filtered_and_paged_in_the_database(library: Library) -> None:
    head = library.head
    await create_book(head, library.class_id, title="New Countdown 5", publisher="Oxford")
    await create_book(head, library.class_id, title="Science Today", publisher="Oxford")
    await create_book(head, library.class_id, title="Urdu Reader", publisher="Gohar")

    async def titles(**query: Any) -> tuple[list[str], int]:
        response = await head.get(f"{API}/books", params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        return [b["title"] for b in body["items"]], body["meta"]["total"]

    # Title or publisher, case-insensitively.
    assert await titles(q="countdown") == (["New Countdown 5"], 1)
    assert sorted((await titles(q="OXFORD"))[0]) == ["New Countdown 5", "Science Today"]
    # Wildcards in the term are literal.
    assert await titles(q="%") == ([], 0)
    # The class filter narrows in SQL too.
    assert (await titles(class_id=library.class_id))[1] == 3

    # Offset paging: newest first, two per page, the total counts every match.
    first, total = await titles(size=2, page=1)
    second, _ = await titles(size=2, page=2)
    assert total == 3
    assert first == ["Urdu Reader", "Science Today"]
    assert second == ["New Countdown 5"]
