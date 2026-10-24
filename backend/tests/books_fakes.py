"""A deterministic stand-in for the OpenAI book agent, and test fixtures for it.

The fake makes the same KINDS of decisions as the real agent, from markers the
tests write into the pages, so the pipeline's rules are tested without a network:

    page images      `make_photo(i)` draws an image `400 + i` pixels wide; the fake
                     "reads" it by looking the width up in `PHOTO_PAGES`.
    "[CH n]"         the chapter a page belongs to (absent = none of the list).
    "[OPENS]"        the page opens a chapter.
    "[AFTER n]"      an unnumbered page continues the page printed `n`.

`answer_question` "answers" from the first passage it is given and cites it, and
says the books do not cover a question containing "[UNCOVERED]" -- the passages
it saw are kept in `ANSWERED` for the tests to inspect.

`read_front_matter` reads lines like "TITLE: ...", "PUBLISHER: ...", "VERSION:
...", "CLASS: ...", "SUBJECT: ..." and "CH n: title" off each page (its PDF text
layer, or the photo's `PHOTO_PAGES` text), and picks the offered class or subject
whose name is printed exactly. What it was offered is kept in `FRONT_MATTER_OFFERS`.

Embeddings hash each word into one of 1536 buckets, so texts sharing words are
close in cosine distance -- enough to prove pgvector search returns the right chunk.

`FakeBatchAgent` adds the Batch API, for page reads and for chunk embeddings: a
batch stays unfinished until the test sets `FAKE_BATCHES[id].done`, and a test
can delete one of its readings or vectors to model a request the batch never
answered.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass, field

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.modules.books.agent import (
    NONE_CHOICE,
    BookAnswer,
    BookContext,
    ChapterVerdict,
    EmbedRequest,
    FrontMatterChapter,
    FrontMatterReading,
    FrontPage,
    PageEvidence,
    PageReading,
    PageVerdict,
    Passage,
    ReadRequest,
    Usage,
)

DIMENSIONS = 1536


@dataclass(frozen=True)
class PhotoPage:
    printed: int | None
    text: str


PHOTO_PAGES: dict[int, PhotoPage] = {}
"""Filled by tests: photo index -> what the fake "reads" from it."""


def make_photo(index: int) -> bytes:
    """A JPEG whose width identifies it to `FakeBookAgent.read_page`."""
    image = Image.new("RGB", (400 + index, 300), color=(240, 240, 240))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def read_photo(image: bytes) -> PageReading:
    with Image.open(io.BytesIO(image)) as img:
        index = img.width - 400
    page = PHOTO_PAGES[index]
    return PageReading(printed_page_number=page.printed, text=page.text)


def make_pdf(pages: Sequence[tuple[int | None, str]]) -> bytes:
    """A real PDF with a text layer: one page per (printed number, body text)."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    for printed, body in pages:
        y = 800
        for paragraph in body.split("\n"):
            # Wrapped: pdfium's bounded text extraction clips at the page edge.
            for line in textwrap.wrap(paragraph, 90) or [""]:
                pdf.drawString(50, y, line)
                y -= 16
        if printed is not None:
            pdf.drawString(290, 30, str(printed))
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def embed_text(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"[a-z]{3,}", text.lower()):
        bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS
        vector[bucket] += 1.0
    if not any(vector):
        vector[0] = 1.0  # pgvector cannot take a cosine distance to a zero vector
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector]


def _marker(text: str, name: str) -> int | None:
    match = re.search(rf"\[{name} (\d+)\]", text)
    return int(match.group(1)) if match else None


class FakeBookAgent:
    def __init__(self) -> None:
        self.usage = Usage()
        self.models = {"read": "fake-read", "decide": "fake-decide", "embed": "fake-embed"}
        self.placement_questions: list[str] = []

    async def read_page(self, image: bytes, image_type: str) -> PageReading:
        self.usage.add("read", 100, 50)
        return read_photo(image)

    async def classify_pages(
        self, ctx: BookContext, pages: Sequence[PageEvidence]
    ) -> list[PageVerdict]:
        self.usage.add("decide", 10 * len(pages))
        return [PageVerdict(_marker(p.text, "CH"), 0.95, "[OPENS]" in p.text) for p in pages]

    async def identify_chapter(
        self, ctx: BookContext, pages: Sequence[PageEvidence]
    ) -> ChapterVerdict:
        self.usage.add("decide", 10)
        for page in pages:
            number = _marker(page.text, "CH")
            if number is not None:
                return ChapterVerdict(number, 0.93, {str(number): 0.93})
        return ChapterVerdict(None, 0.8, {"none": 0.8})

    async def place_pages(
        self, pages: Sequence[PageEvidence], unplaced: Sequence[str]
    ) -> dict[str, str | None]:
        self.placement_questions.extend(unplaced)
        by_printed = {p.printed_page_number: p.label for p in pages if p.printed_page_number}
        texts = {p.label: p.text for p in pages}
        result: dict[str, str | None] = {}
        for label in unplaced:
            after = _marker(texts[label], "AFTER")
            if after is None:
                result[label] = None
            elif after in by_printed:
                result[label] = by_printed[after]
        return result

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.usage.add("embed", sum(len(t) // 4 for t in texts))
        return [embed_text(t) for t in texts]

    async def answer_question(self, question: str, passages: Sequence[Passage]) -> BookAnswer:
        self.usage.add("answer", 100, 20)
        ANSWERED.append((question, list(passages)))
        if "[UNCOVERED]" in question:
            return BookAnswer(found=False, answer="Not in these books.", citations=[])
        first = passages[0]
        return BookAnswer(found=True, answer=f"{first.text[:60]} [1]", citations=[1])

    async def read_front_matter(
        self, pages: Sequence[FrontPage], classes: Sequence[str], subjects: Sequence[str]
    ) -> FrontMatterReading:
        self.usage.add("front_matter", 500 * len(pages), 200)
        FRONT_MATTER_OFFERS.append((list(classes), list(subjects)))
        text = "\n".join(p.text_layer or read_photo(p.image).text for p in pages)
        fields = dict(re.findall(r"^([A-Z]+): (.+)$", text, re.M))
        class_printed, subject_printed = fields.get("CLASS"), fields.get("SUBJECT")
        return FrontMatterReading(
            title=fields.get("TITLE"),
            publisher=fields.get("PUBLISHER"),
            version=fields.get("VERSION"),
            class_printed=class_printed,
            class_choice=class_printed if class_printed in classes else NONE_CHOICE,
            subject_printed=subject_printed,
            subject_choice=subject_printed if subject_printed in subjects else NONE_CHOICE,
            chapters=[
                FrontMatterChapter(number=int(number), title=title)
                for number, title in re.findall(r"^CH (\d+): (.+)$", text, re.M)
            ],
        )

    async def check(self) -> str | None:
        return SCAN_PROBLEM[0]


SCAN_PROBLEM: list[str | None] = [None]
"""What the fake reader's `check` reports; a test sets `SCAN_PROBLEM[0]`."""
ANSWERED: list[tuple[str, list[Passage]]] = []
"""Every (question, passages) `answer_question` was given. Module-level: the API
builds a new agent per request."""
FRONT_MATTER_OFFERS: list[tuple[list[str], list[str]]] = []
"""Every (classes, subjects) `read_front_matter` was offered."""


@dataclass
class FakeBatch:
    readings: dict[str, PageReading] = field(default_factory=dict)
    vectors: dict[str, list[float]] = field(default_factory=dict)
    done: bool = False


FAKE_BATCHES: dict[str, FakeBatch] = {}
"""Module-level, like OpenAI's own batches: the worker builds a new agent per pass."""
DISCARDED_BATCHES: list[str] = []


class FakeBatchAgent(FakeBookAgent):
    def __init__(self) -> None:
        super().__init__()
        self.submitted: list[str] = []

    async def submit_reads(self, pages: Sequence[ReadRequest], *, label: str) -> list[str]:
        batch_id = f"batch_{len(FAKE_BATCHES) + 1}"
        FAKE_BATCHES[batch_id] = FakeBatch(readings={p.key: read_photo(p.image) for p in pages})
        self.submitted.append(batch_id)
        return [batch_id]

    async def submit_embeddings(self, chunks: Sequence[EmbedRequest], *, label: str) -> list[str]:
        batch_id = f"batch_{len(FAKE_BATCHES) + 1}"
        FAKE_BATCHES[batch_id] = FakeBatch(vectors={c.key: embed_text(c.text) for c in chunks})
        self.submitted.append(batch_id)
        return [batch_id]

    async def batches_ready(self, batch_ids: Sequence[str]) -> bool:
        return all(FAKE_BATCHES[i].done for i in batch_ids)

    async def collect_reads(self, batch_ids: Sequence[str]) -> dict[str, PageReading]:
        readings: dict[str, PageReading] = {}
        for batch_id in batch_ids:
            for key, reading in FAKE_BATCHES[batch_id].readings.items():
                self.usage.add("read_batch", 100, 50)
                readings[key] = reading
        return readings

    async def collect_embeddings(self, batch_ids: Sequence[str]) -> dict[str, list[float]]:
        vectors: dict[str, list[float]] = {}
        for batch_id in batch_ids:
            for key, vector in FAKE_BATCHES[batch_id].vectors.items():
                self.usage.add("embed_batch", 50)
                vectors[key] = vector
        return vectors

    async def discard_batches(self, batch_ids: Sequence[str]) -> None:
        DISCARDED_BATCHES.extend(batch_ids)
