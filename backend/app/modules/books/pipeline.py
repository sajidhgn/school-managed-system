"""The book agent's procedure for one chapter: read, order, verify, chunk, embed.

WHY THIS FILE EXISTS
    This is the agent's reasoning, written down as code: which evidence wins when
    two signals disagree, when a model is asked at all, and what counts as "a
    teacher should look at this". It takes bytes in and returns plain data out --
    no database, no storage -- so every rule here is tested with a fake agent.

THE STEPS
    1. SPLIT    every upload into pages (`ingest.py`, in a thread).
    2. READ     each page: the PDF's own text when it is usable (free), else the
                vision model. Either way the printed page number is captured.
                With batch reading the vision results arrive as `readings`,
                collected beforehand (`pages_to_read` lists what to submit); a
                page the batch did not answer is read live here.
    3. ORDER    by printed page number. An unnumbered page inside a PDF stays
                after the page before it in that PDF; an unnumbered loose photo
                is placed by a Decisions API continuity question ("which page
                does this one follow?"). Only then is upload order used.
    4. VERIFY   against the book's chapter list, with the Decisions API:
                  * which chapter is the upload as a whole?
                  * which chapter is each page from, and does it open a chapter?
                Plus deterministic checks: duplicate and missing page numbers,
                pages with no readable text.
    5. CHUNK    the ordered text into ~600-token passages that remember their pages.
    6. EMBED    every chunk -- unless `embed=False`, when the worker hands the
                chunks to an embedding batch after saving the chapter.

    Any issue from step 4 makes the chapter NEEDS_REVIEW rather than READY. It is
    still indexed: the teacher's review is about trust, not about whether the text
    exists, and "accept" is one click.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.books.agent import BookAgent, BookContext, PageEvidence, PageReading, ReadRequest
from app.modules.books.ingest import (
    RawPage,
    guess_printed_page_number,
    split_file,
    text_layer_is_usable,
)
from app.modules.books.models import ChapterStatus, FileKind, PageMethod, PagePlacement

MATCH_THRESHOLD = 0.6
"""Below this, a chapter match is not trusted without a teacher looking."""
_MAX_REPORTED_GAP = 50
_CHUNK_TARGET_CHARS = 2400
_CHUNK_MAX_CHARS = 3200
_OVERLAP_MAX_CHARS = 600


@dataclass(frozen=True, slots=True)
class SourceFile:
    id: UUID
    kind: FileKind
    sort_order: int
    data: bytes


@dataclass
class WorkingPage:
    label: str
    file_id: UUID
    file_kind: FileKind
    file_is_single: bool
    """True when this file is the chapter's only upload."""
    source_index: int
    upload_index: int
    image: bytes
    image_type: str
    text: str = ""
    method: PageMethod = PageMethod.TEXT_LAYER
    printed_page_number: int | None = None
    placement: PagePlacement = PagePlacement.UPLOAD_ORDER
    position: int = 0
    detected_chapter_number: int | None = None
    chapter_confidence: float | None = None
    opens_chapter: bool = False

    @property
    def key(self) -> str:
        """Stable across re-splits of the same files -- a batch request's `custom_id`."""
        return f"{self.file_id}:{self.source_index}"

    def needs_vision(self) -> bool:
        return not (self.file_kind is FileKind.PDF and text_layer_is_usable(self.text))

    def evidence(self) -> PageEvidence:
        return PageEvidence(self.label, self.text, self.printed_page_number)


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    index: int
    page_start: int
    page_end: int
    printed_start: int | None
    printed_end: int | None
    content: str
    embedding: list[float] = field(default_factory=list)
    """Empty when the chunk is left for an embedding batch."""


@dataclass
class PipelineResult:
    pages: list[WorkingPage]
    chunks: list[ChunkDraft]
    status: ChapterStatus
    report: dict[str, Any]


def _issue(code: str, message: str, positions: list[int] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "positions": positions or []}


async def pages_to_read(files: list[SourceFile]) -> list[ReadRequest]:
    """The pages a run would send to the vision model -- what a batch must cover."""
    return [
        ReadRequest(p.key, p.image, p.image_type) for p in await _split(files) if p.needs_vision()
    ]


async def run_pipeline(
    ctx: BookContext,
    files: list[SourceFile],
    agent: BookAgent,
    readings: Mapping[str, PageReading] | None = None,
    *,
    embed: bool = True,
) -> PipelineResult:
    pages = await _split(files)
    if not pages:
        raise ValueError("The uploaded files contain no pages.")

    batch_read, read_live = await _read(pages, agent, readings or {})
    issues: list[dict[str, Any]] = []
    await _order(pages, agent, issues)
    detected = await _verify(ctx, pages, agent, issues)

    chunks = chunk_pages(pages)
    if chunks and embed:
        vectors = await agent.embed([c.content for c in chunks])
        chunks = [
            ChunkDraft(
                c.index, c.page_start, c.page_end, c.printed_start, c.printed_end, c.content, v
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
    elif not chunks:
        issues.append(_issue("no_text", "No text could be read from any page of this chapter."))

    status = ChapterStatus.NEEDS_REVIEW if issues else ChapterStatus.READY
    report = {
        "detected_chapter_number": detected[0],
        "detected_confidence": round(detected[1], 3),
        "matches_declared": detected[0] == ctx.declared.number,
        "chapter_probabilities": detected[2],
        "issues": issues,
        "pages_total": len(pages),
        "vision_pages": sum(p.method is PageMethod.VISION for p in pages),
        "text_layer_pages": sum(p.method is PageMethod.TEXT_LAYER for p in pages),
        "batch_read_pages": batch_read,
        "batch_fallback_pages": read_live if readings is not None else 0,
        "chunks": len(chunks),
        "models": dict(agent.models),
        "calls": dict(agent.usage.calls),
        "input_tokens": agent.usage.input_tokens,
        "output_tokens": agent.usage.output_tokens,
    }
    return PipelineResult(pages, chunks, status, report)


# -- 1. split ------------------------------------------------------------------


async def _split(files: list[SourceFile]) -> list[WorkingPage]:
    ordered = sorted(files, key=lambda f: f.sort_order)
    split: list[list[RawPage]] = await asyncio.gather(
        *(asyncio.to_thread(split_file, f.data, f.kind) for f in ordered)
    )
    pages: list[WorkingPage] = []
    for source, raws in zip(ordered, split, strict=True):
        for raw in raws:
            pages.append(
                WorkingPage(
                    label=f"P{len(pages) + 1}",
                    file_id=source.id,
                    file_kind=source.kind,
                    file_is_single=len(ordered) == 1,
                    source_index=raw.source_index,
                    upload_index=len(pages),
                    image=raw.image,
                    image_type=raw.image_type,
                    text=raw.text_layer,
                )
            )
    return pages


# -- 2. read -------------------------------------------------------------------


async def _read(
    pages: list[WorkingPage], agent: BookAgent, readings: Mapping[str, PageReading]
) -> tuple[int, int]:
    """Fill in every page's text. Returns (pages read by batch, pages read live)."""
    from_batch = 0
    live = 0

    async def read_one(page: WorkingPage) -> None:
        nonlocal from_batch, live
        if not page.needs_vision():
            page.method = PageMethod.TEXT_LAYER
            page.printed_page_number = guess_printed_page_number(page.text)
            return
        reading = readings.get(page.key)
        if reading is None:
            reading = await agent.read_page(page.image, page.image_type)
            live += 1
        else:
            from_batch += 1
        page.method = PageMethod.VISION
        page.text = reading.text.strip()
        page.printed_page_number = reading.printed_page_number

    await asyncio.gather(*(read_one(p) for p in pages))
    return from_batch, live


# -- 3. order ------------------------------------------------------------------


async def _order(pages: list[WorkingPage], agent: BookAgent, issues: list[dict[str, Any]]) -> None:
    by_file_index = {(p.file_id, p.source_index): p for p in pages}
    numbered = sorted(
        (p for p in pages if p.printed_page_number is not None),
        key=lambda p: (p.printed_page_number, p.upload_index),
    )
    for p in numbered:
        p.placement = PagePlacement.PRINTED_NUMBER

    # predecessor label per unnumbered page; None = goes first
    after: dict[str, str | None] = {}
    ask: list[WorkingPage] = []
    for p in pages:
        if p.printed_page_number is not None:
            continue
        previous = by_file_index.get((p.file_id, p.source_index - 1))
        if p.file_kind is FileKind.PDF and previous is not None:
            after[p.label] = previous.label
            p.placement = PagePlacement.PDF_ORDER
        elif p.file_is_single:
            after[p.label] = None  # the first page of the only file
            p.placement = PagePlacement.PDF_ORDER
        else:
            ask.append(p)

    if ask and len(pages) > 1:
        decided = await agent.place_pages([q.evidence() for q in pages], [q.label for q in ask])
        valid = {p.label for p in pages}
        for p in ask:
            if p.label in decided and (decided[p.label] is None or decided[p.label] in valid):
                after[p.label] = decided[p.label]
                p.placement = PagePlacement.AGENT

    sequence = [p.label for p in numbered]
    pending = dict(after)
    leftovers = [p.label for p in ask if p.label not in after]

    starts = [label for label, pred in pending.items() if pred is None]
    sequence = starts + sequence
    for label in starts:
        del pending[label]
    # Insert pages whose predecessor is already placed, until nothing moves. A page
    # placed after X goes after X and after any page already chained behind X, so
    # two photos that both "follow page 12" keep their upload order.
    progress = True
    while pending and progress:
        progress = False
        for label, pred in list(pending.items()):
            if pred in sequence:
                sequence.insert(
                    sequence.index(pred) + 1 + _chain_after(sequence, pred, after), label
                )
                del pending[label]
                progress = True
    leftovers.extend(pending)  # cycles the model produced, if any

    lookup = {p.label: p for p in pages}
    for label in sorted(leftovers, key=lambda lbl: lookup[lbl].upload_index):
        lookup[label].placement = PagePlacement.UPLOAD_ORDER
        sequence.append(label)
    if leftovers:
        issues.append(
            _issue(
                "unplaced_pages",
                f"{len(leftovers)} page(s) had no page number and could not be placed; "
                "they were put at the end.",
            )
        )

    for position, label in enumerate(sequence, start=1):
        lookup[label].position = position
    pages.sort(key=lambda p: p.position)
    _numbering_issues(pages, issues)


def _chain_after(sequence: list[str], pred: str, after: dict[str, str | None]) -> int:
    """How many pages directly behind `pred` were themselves placed after `pred`."""
    count = 0
    index = sequence.index(pred) + 1
    while index < len(sequence) and after.get(sequence[index]) == pred:
        count += 1
        index += 1
    return count


def _numbering_issues(pages: list[WorkingPage], issues: list[dict[str, Any]]) -> None:
    seen: dict[int, list[int]] = {}
    for p in pages:
        if p.printed_page_number is not None:
            seen.setdefault(p.printed_page_number, []).append(p.position)
    for number, positions in sorted(seen.items()):
        if len(positions) > 1:
            issues.append(
                _issue(
                    "duplicate_page_number",
                    f"Page {number} appears {len(positions)} times -- probably uploaded twice.",
                    positions,
                )
            )

    previous: WorkingPage | None = None
    unnumbered_between = 0
    for p in pages:
        if p.printed_page_number is None:
            unnumbered_between += 1
            continue
        if previous is not None and previous.printed_page_number is not None:
            gap = p.printed_page_number - previous.printed_page_number - 1
            missing = gap - unnumbered_between
            if missing > 0 and gap <= _MAX_REPORTED_GAP:
                first = previous.printed_page_number + 1
                last = p.printed_page_number - 1
                span = f"page {first}" if first == last else f"pages {first}-{last}"
                issues.append(
                    _issue(
                        "missing_pages",
                        f"Nothing was uploaded for {span}"
                        + (f" ({missing} page(s) missing)." if unnumbered_between else "."),
                        [previous.position, p.position],
                    )
                )
            elif gap > _MAX_REPORTED_GAP:
                issues.append(
                    _issue(
                        "numbering_jump",
                        f"Page numbers jump from {previous.printed_page_number} to "
                        f"{p.printed_page_number}.",
                        [previous.position, p.position],
                    )
                )
        previous = p
        unnumbered_between = 0


# -- 4. verify -----------------------------------------------------------------


async def _verify(
    ctx: BookContext, pages: list[WorkingPage], agent: BookAgent, issues: list[dict[str, Any]]
) -> tuple[int | None, float, dict[str, float]]:
    evidence = [p.evidence() for p in pages]
    upload, verdicts = await asyncio.gather(
        agent.identify_chapter(ctx, evidence), agent.classify_pages(ctx, evidence)
    )
    for page, verdict in zip(pages, verdicts, strict=True):
        page.detected_chapter_number = verdict.chapter_number
        page.chapter_confidence = round(verdict.confidence, 3)
        page.opens_chapter = verdict.opens_chapter

    titles = {c.number: c.title for c in ctx.chapters}
    declared = ctx.declared
    if upload.chapter_number != declared.number:
        if upload.chapter_number is None:
            found = "does not match any chapter in the chapter list"
        else:
            found = (
                f"looks like Chapter {upload.chapter_number}: "
                f"{titles.get(upload.chapter_number, '?')} ({upload.confidence:.0%})"
            )
        issues.append(
            _issue(
                "chapter_mismatch",
                f"This upload {found}, not Chapter {declared.number}: {declared.title}.",
            )
        )
    elif upload.confidence < MATCH_THRESHOLD:
        issues.append(
            _issue(
                "low_confidence",
                f"Only {upload.confidence:.0%} sure this is Chapter {declared.number}.",
            )
        )

    foreign = [
        p
        for p in pages
        if p.detected_chapter_number != declared.number
        and (p.chapter_confidence or 0) >= MATCH_THRESHOLD
        and p.text
    ]
    if foreign:
        described = ", ".join(
            f"#{p.position} ({_chapter_label(p.detected_chapter_number)})" for p in foreign[:10]
        )
        issues.append(
            _issue(
                "foreign_pages",
                f"{len(foreign)} page(s) look like they belong elsewhere: {described}.",
                [p.position for p in foreign],
            )
        )

    openers = [p for p in pages if p.opens_chapter]
    if len(openers) > 1:
        issues.append(
            _issue(
                "several_chapter_openings",
                f"{len(openers)} pages look like the first page of a chapter -- the upload "
                "may contain more than one chapter.",
                [p.position for p in openers],
            )
        )

    blank = [p.position for p in pages if not p.text.strip()]
    if blank:
        issues.append(
            _issue("unreadable_pages", f"{len(blank)} page(s) had no readable text.", blank)
        )

    return upload.chapter_number, upload.confidence, upload.probabilities


def _chapter_label(number: int | None) -> str:
    return "no listed chapter" if number is None else f"Ch {number}"


# -- 5. chunk ------------------------------------------------------------------

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def chunk_pages(pages: list[WorkingPage]) -> list[ChunkDraft]:
    """Split the chapter's ordered text into passages of about 600 tokens.

    Paragraph boundaries are respected (a paragraph longer than the maximum is cut
    on sentence ends), and each chunk repeats the previous chunk's last short
    paragraph, so an answer that straddles a boundary is still retrievable whole.
    """
    paragraphs: list[tuple[int, int | None, str]] = []
    for p in sorted(pages, key=lambda x: x.position):
        for para in _PARAGRAPH_SPLIT.split(p.text):
            para = para.strip()
            if not para:
                continue
            for piece in _split_long(para):
                paragraphs.append((p.position, p.printed_page_number, piece))

    chunks: list[ChunkDraft] = []
    current: list[tuple[int, int | None, str]] = []
    size = 0

    def emit() -> None:
        printed = [pr for _, pr, _ in current if pr is not None]
        chunks.append(
            ChunkDraft(
                index=len(chunks),
                page_start=current[0][0],
                page_end=current[-1][0],
                printed_start=min(printed) if printed else None,
                printed_end=max(printed) if printed else None,
                content="\n\n".join(text for _, _, text in current),
            )
        )

    fresh = False  # whether `current` holds anything beyond the carried-over overlap
    for item in paragraphs:
        if fresh and size + len(item[2]) > _CHUNK_TARGET_CHARS:
            emit()
            tail = current[-1]
            current, size = (
                ([tail], len(tail[2])) if len(tail[2]) <= _OVERLAP_MAX_CHARS else ([], 0)
            )
        current.append(item)
        size += len(item[2]) + 2
        fresh = True
    if fresh:
        emit()
    return chunks


def _split_long(paragraph: str) -> list[str]:
    if len(paragraph) <= _CHUNK_MAX_CHARS:
        return [paragraph]
    # \u06d4 is the Urdu full stop.
    sentences = re.split(r"(?<=[.!?\u06d4])\s+", paragraph)
    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        while len(sentence) > _CHUNK_MAX_CHARS:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.append(sentence[:_CHUNK_MAX_CHARS])
            sentence = sentence[_CHUNK_MAX_CHARS:]
        if len(buffer) + len(sentence) + 1 > _CHUNK_MAX_CHARS:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer:
        pieces.append(buffer)
    return pieces
