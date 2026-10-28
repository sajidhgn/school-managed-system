"""PostgreSQL tests for test papers and the question bank.

What a mocked suite would pass without:

  * THE WHOLE LOOP. A chapter is uploaded and read by the book worker; a paper is
    requested through the API, claimed by the real worker
    (`process_pending_papers`) as the restricted `sms_app` role, written from
    that chapter's saved text, and reviewed, edited, replaced and regenerated.
  * ORDER. Sections print objective first; positions stay 1..n through every
    removal and addition.
  * NO SPILL-OVER. Editing a question another paper also uses edits a copy.
  * URDU AND ARABIC. A paper asks the writer for its language and prints that
    language's true/false words.
  * OWNERSHIP AND ISOLATION. `paper:write` changes only your own papers; another
    organization sees nothing -- and writes a paper from a book only once it has
    added the book from the shared library, the paper then being its own.

The model calls are the fakes in `tests/books_fakes.py` and `tests/papers_fakes.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.common.email.sender import EmailMessage
from app.modules.papers.jobs import process_pending_papers
from app.modules.papers.models import Difficulty, PaperLanguage
from app.modules.papers.router import get_paper_agent_factory
from tests.books_fakes import make_pdf
from tests.integration.conftest import API, Tenant
from tests.integration.test_academic_foundation import build_campus
from tests.integration.test_books import (
    BODY,
    Actor,
    Library,
    build_library,
    chapter,
    create_book,
    upload,
)
from tests.papers_fakes import FAKE_PAPER, FakePaperAgent

pytestmark = pytest.mark.asyncio

MIX = {
    "paper_type": "mix",
    "difficulty": "mixed",
    "sections": [
        {"type": "long", "count": 1},
        {"type": "mcq", "count": 5},
        {"type": "short", "count": 3},
        {"type": "true_false", "count": 2},
    ],
}


async def generate() -> dict[str, int]:
    return await process_pending_papers(limit=10, agent_factory=FakePaperAgent)


@pytest.fixture
async def library(tenant: Tenant, mailbox: list[EmailMessage], tmp_path: Path) -> Library:
    return await build_library(tenant, mailbox, tmp_path)


@pytest.fixture
async def ready_book(library: Library) -> dict[str, Any]:
    """A book whose chapter 2 has been read; chapter 1 has nothing uploaded."""
    FAKE_PAPER.reset()
    app = library.tenant.client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_paper_agent_factory] = lambda: FakePaperAgent
    book = await create_book(library.teacher, library.class_id)
    pdf = make_pdf(
        [
            (21, f"[CH 2] [OPENS] Chapter 2: Fractions. {BODY * 3}"),
            (22, f"[CH 2] Equivalent fractions name the same amount. {BODY * 3}"),
        ]
    )
    uploaded = await upload(
        library.teacher, book, 2, [("files", ("chapter-2.pdf", pdf, "application/pdf"))]
    )
    assert uploaded.status_code == 200, uploaded.text
    assert await library.process() == {"ready": 1}
    return book


async def request_paper(
    library: Library, book: dict[str, Any], *, chapters: tuple[int, ...] = (2,), **body: Any
) -> Any:
    return await library.teacher.post(
        f"{API}/papers",
        json={
            "title": "Unit Test 1",
            "book_id": book["id"],
            "chapter_ids": [chapter(book, n)["id"] for n in chapters],
            **{**MIX, **body},
        },
    )


async def test_a_teacher_generates_reviews_and_edits_a_paper(
    library: Library, ready_book: dict[str, Any]
) -> None:
    book = ready_book
    unread = await request_paper(library, book, chapters=(1,))
    assert unread.status_code == 422, unread.text
    assert unread.json()["code"] == "CHAPTER_NOT_READY"
    wrong_type = await request_paper(
        library,
        book,
        paper_type="objective",
        sections=[{"type": "short", "count": 2}],
    )
    assert wrong_type.status_code == 422, wrong_type.text

    created = await request_paper(library, book, duration_minutes=60)
    assert created.status_code == 201, created.text
    paper = created.json()
    assert paper["status"] == "queued" and paper["sections"] == []
    assert [s["type"] for s in paper["requested"]] == ["mcq", "true_false", "short", "long"]
    assert [s["marks"] for s in paper["requested"]] == [1, 1, 2, 5], "usual marks per type"
    url = f"{API}/papers/{paper['id']}"

    busy = await library.teacher.patch(url, json={"title": "Too soon"})
    assert busy.status_code == 409 and busy.json()["code"] == "PAPER_BUSY"

    assert await generate() == {"paper_ready": 1}
    assert await generate() == {}, "nothing left to claim"

    detail = (await library.teacher.get(url)).json()
    assert detail["status"] == "ready", detail["report"]
    assert [s["type"] for s in detail["sections"]] == ["mcq", "true_false", "short", "long"]
    assert [len(s["questions"]) for s in detail["sections"]] == [5, 2, 3, 1]
    assert detail["question_count"] == 11 and detail["total_marks"] == 5 + 2 + 6 + 5
    positions = [q["position"] for s in detail["sections"] for q in s["questions"]]
    assert positions == list(range(1, 12))
    first = detail["sections"][0]["questions"][0]
    assert first["requested_difficulty"] == "easy"
    assert first["question"]["chapter_number"] == 2
    assert first["question"]["printed_page"] == 21
    assert first["question"]["checks"]["answerable"] == 0.95
    assert len(first["question"]["options"]) == 4
    assert detail["report"]["chosen"] == 11 and detail["report"]["issues"] == []
    assert detail["chapters"] == [{"id": chapter(book, 2)["id"], "number": 2, "title": "Fractions"}]

    listed = (await library.teacher.get(f"{API}/papers")).json()["items"]
    assert [(p["id"], p["question_count"]) for p in listed] == [(paper["id"], 11)]

    # The list is searched and paged in the database: title search, and a page
    # carries the total of every match, not just the rows on it.
    page = (await library.teacher.get(f"{API}/papers", params={"q": "unit TEST"})).json()
    assert [p["id"] for p in page["items"]] == [paper["id"]]
    assert page["meta"]["total"] == 1
    none = (await library.teacher.get(f"{API}/papers", params={"q": "%"})).json()
    assert none["items"] == [] and none["meta"]["total"] == 0
    bank_page = (
        await library.teacher.get(f"{API}/papers/questions", params={"size": 4, "page": 2})
    ).json()
    assert len(bank_page["items"]) == 4
    assert bank_page["meta"]["total"] == 11 and bank_page["meta"]["has_next"] is True

    # -- edit: options are checked against the type; the edit is marked manual.
    entry = first["id"]
    bad = await library.teacher.patch(
        f"{url}/questions/{entry}", json={"options": ["a", "b", "c"], "correct_option": 0}
    )
    assert bad.status_code == 422, bad.text
    edited = await library.teacher.patch(
        f"{url}/questions/{entry}",
        json={"text": "Which fraction equals 1/2?", "marks": 2},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["question"]["text"] == "Which fraction equals 1/2?"
    assert edited.json()["question"]["origin"] == "manual"
    assert edited.json()["marks"] == 2

    # -- remove: the positions close up; the question stays in the bank.
    removed_entry = detail["sections"][2]["questions"][0]
    gone = await library.teacher.delete(f"{url}/questions/{removed_entry['id']}")
    assert gone.status_code == 204, gone.text
    after = (await library.teacher.get(url)).json()
    assert [q["position"] for s in after["sections"] for q in s["questions"]] == list(range(1, 11))
    bank = (await library.teacher.get(f"{API}/papers/questions", params={"type": "short"})).json()[
        "items"
    ]
    assert removed_entry["question"]["id"] in {q["id"] for q in bank}

    # -- add it back from the bank: it lands at the end of its own section.
    added = await library.teacher.post(
        f"{url}/questions", json={"question_id": removed_entry["question"]["id"]}
    )
    assert added.status_code == 201, added.text
    assert added.json()["position"] == 10, "after the two remaining shorts, before the long"
    again = await library.teacher.post(
        f"{url}/questions", json={"question_id": removed_entry["question"]["id"]}
    )
    assert again.status_code == 409 and again.json()["code"] == "DUPLICATE_QUESTION"

    # -- replace: the agent writes a different question for the same place.
    target = after["sections"][2]["questions"][0]
    replaced = await library.teacher.post(
        f"{url}/questions/{target['id']}/replace", json={"difficulty": "hard"}
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["position"] == target["position"]
    assert replaced.json()["question"]["id"] != target["question"]["id"]
    assert replaced.json()["requested_difficulty"] == "hard"
    request = FAKE_PAPER.requests[-1]
    assert request.counts == {Difficulty.HARD: 2} and len(request.avoid) == 11

    # -- ownership: another teacher sees the paper but cannot change it.
    seen = await library.other_teacher.get(url)
    assert seen.status_code == 200 and seen.json()["can_edit"] is False
    refused = await library.other_teacher.patch(url, json={"title": "Mine now"})
    assert refused.status_code == 403 and refused.json()["code"] == "PAPER_NOT_OWNED"
    managed = await library.head.patch(url, json={"title": "Unit Test 1 (final)"})
    assert managed.status_code == 200 and managed.json()["title"] == "Unit Test 1 (final)"

    # -- regenerate: the paper is written again; old questions stay in the bank.
    regenerated = await library.teacher.post(f"{url}/regenerate")
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["status"] == "queued" and regenerated.json()["sections"] == []
    assert await generate() == {"paper_ready": 1}
    assert (await library.teacher.get(url)).json()["question_count"] == 11


async def test_editing_a_shared_question_never_changes_the_other_paper(
    library: Library, ready_book: dict[str, Any]
) -> None:
    objective = {
        "paper_type": "objective",
        "difficulty": "easy",
        "sections": [{"type": "mcq", "count": 2}],
    }
    first = (await request_paper(library, ready_book, **objective)).json()
    second = (await request_paper(library, ready_book, **objective)).json()
    assert await generate() == {"paper_ready": 2}
    first_url, second_url = f"{API}/papers/{first['id']}", f"{API}/papers/{second['id']}"
    shared = (await library.teacher.get(first_url)).json()["sections"][0]["questions"][0]

    added = await library.teacher.post(
        f"{second_url}/questions", json={"question_id": shared["question"]["id"]}
    )
    assert added.status_code == 201, added.text
    edited = await library.teacher.patch(
        f"{second_url}/questions/{added.json()['id']}",
        json={
            "options": ["one half", "two quarters", "three thirds", "four fifths"],
            "correct_option": 0,
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["question"]["id"] != shared["question"]["id"], "edited a copy"
    untouched = (await library.teacher.get(first_url)).json()["sections"][0]["questions"][0]
    assert untouched["question"]["options"] == shared["question"]["options"]


async def test_an_urdu_paper_is_written_in_urdu(
    library: Library, ready_book: dict[str, Any]
) -> None:
    created = await request_paper(
        library,
        ready_book,
        language="ur",
        paper_type="objective",
        difficulty="medium",
        sections=[{"type": "true_false", "count": 2}, {"type": "fill_blank", "count": 1}],
    )
    assert created.status_code == 201, created.text
    assert await generate() == {"paper_ready": 1}
    detail = (await library.teacher.get(f"{API}/papers/{created.json()['id']}")).json()
    assert detail["language"] == "ur"
    true_false = detail["sections"][0]["questions"][0]["question"]
    assert true_false["language"] == "ur"
    assert true_false["options"] == ["درست", "غلط"]
    assert "درست یا غلط" in true_false["text"]
    assert {r.language for r in FAKE_PAPER.requests} == {PaperLanguage.URDU}
    urdu_bank = await library.teacher.get(f"{API}/papers/questions", params={"language": "ur"})
    assert len(urdu_bank.json()["items"]) == 3


async def test_an_arabic_paper_is_written_in_arabic(
    library: Library, ready_book: dict[str, Any]
) -> None:
    created = await request_paper(
        library,
        ready_book,
        language="ar",
        paper_type="objective",
        difficulty="easy",
        sections=[{"type": "true_false", "count": 1}],
    )
    assert created.status_code == 201, created.text
    assert await generate() == {"paper_ready": 1}
    detail = (await library.teacher.get(f"{API}/papers/{created.json()['id']}")).json()
    assert detail["language"] == "ar"
    question = detail["sections"][0]["questions"][0]["question"]
    assert question["language"] == "ar"
    assert question["options"] == ["صحيح", "خطأ"]
    assert {r.language for r in FAKE_PAPER.requests} == {PaperLanguage.ARABIC}


async def test_a_paper_the_checks_cannot_fill_needs_review_or_fails(
    library: Library, ready_book: dict[str, Any]
) -> None:
    short = {"paper_type": "subjective", "sections": [{"type": "short", "count": 2}]}
    FAKE_PAPER.judge_as = Difficulty.MEDIUM
    hard = (await request_paper(library, ready_book, difficulty="hard", **short)).json()
    assert await generate() == {"paper_needs_review": 1}
    detail = (await library.teacher.get(f"{API}/papers/{hard['id']}")).json()
    assert [i["code"] for i in detail["report"]["issues"]] == ["difficulty_mismatch"]
    assert detail["question_count"] == 2

    FAKE_PAPER.judge_as = None
    FAKE_PAPER.unanswerable.update(range(1, 50))
    hopeless = (await request_paper(library, ready_book, difficulty="easy", **short)).json()
    assert await generate() == {"paper_failed": 1}
    failed = (await library.teacher.get(f"{API}/papers/{hopeless['id']}")).json()
    assert failed["status"] == "failed" and failed["error"]


async def test_another_organization_cannot_see_a_paper(
    library: Library, ready_book: dict[str, Any], make_tenant: Callable[..., Any]
) -> None:
    created = await request_paper(
        library,
        ready_book,
        paper_type="objective",
        sections=[{"type": "mcq", "count": 1}],
    )
    assert await generate() == {"paper_ready": 1}
    rival: Tenant = await make_tenant(
        name="Rival Trust", email="rival@test.example", school_code="RIVAL"
    )
    assert (await rival.get(f"{API}/papers")).json()["items"] == []
    assert (await rival.get(f"{API}/papers/questions")).json()["items"] == []
    assert (await rival.get(f"{API}/papers/{created.json()['id']}")).status_code == 404
    stolen = await rival.post(
        f"{API}/papers",
        json={
            "title": "Theirs",
            "book_id": ready_book["id"],
            "chapter_ids": [chapter(ready_book, 2)["id"]],
            "paper_type": "objective",
            "sections": [{"type": "mcq", "count": 1}],
        },
    )
    assert stolen.status_code == 404, "a book the campus has not added does not exist"


async def test_a_paper_from_a_library_book_belongs_to_the_school_that_wrote_it(
    library: Library,
    ready_book: dict[str, Any],
    make_tenant: Callable[..., Any],
    mailbox: list[EmailMessage],
) -> None:
    rival: Tenant = await make_tenant(
        name="Rival Trust", email="rival@test.example", school_code="RIVAL"
    )
    campus = await build_campus(rival, mailbox, email="rival-head@test.example", students=0)
    head = Actor(rival.client, campus.headers)
    added = await head.post(
        f"{API}/books/library/{ready_book['id']}", json={"class_id": campus.class_id}
    )
    assert added.status_code == 201, added.text

    created = await head.post(
        f"{API}/papers",
        json={
            "title": "Their test",
            "book_id": ready_book["id"],
            "chapter_ids": [chapter(ready_book, 2)["id"]],
            "paper_type": "objective",
            "sections": [{"type": "mcq", "count": 1}],
        },
    )
    assert created.status_code == 201, created.text
    paper = created.json()
    assert paper["class_id"] == campus.class_id, "filed under the adding school's class"
    assert await generate() == {"paper_ready": 1}, "written from the uploader's pages"
    assert (await head.get(f"{API}/papers/{paper['id']}")).json()["status"] == "ready"

    # The uploading school shares the book, not the papers written from it.
    assert (await library.teacher.get(f"{API}/papers/{paper['id']}")).status_code == 404
    assert (await library.teacher.get(f"{API}/papers")).json()["items"] == []
