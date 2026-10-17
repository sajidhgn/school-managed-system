"""The book worker: claim a queued chapter, run the agent on it, save the result.

HOW IT RUNS
    `python -m app.cli process-books` drains the queue once; `--watch` keeps
    polling (the `book-worker` service in compose). With
    `BOOKS_INLINE_PROCESSING=true` the API also runs a chapter itself straight
    after it is queued -- the same `process_chapter` either way.

THREE TRANSACTIONS PER CHAPTER, NEVER ONE
    Reading a 30-page chapter takes minutes of model calls. Holding a transaction
    (and a row lock) across that would block every edit to the chapter and, on a
    crash, roll back nothing useful. So:

      1. CLAIM   lock the row (`FOR UPDATE SKIP LOCKED`), mark it `processing`,
                 stamp `locked_at`, read the file list. Commit.
      2. WORK    no session open: storage reads, model calls, image writes.
      3. SAVE    lock the row again and write ONLY if it is still `processing`
                 with the same `locked_at`. A teacher who deleted the chapter, or
                 a second worker that re-claimed a stale row, wins -- this run's
                 result is discarded rather than written over theirs.

    A worker that dies mid-run leaves the row `processing`; after `STALE_AFTER`
    another worker re-claims it, up to `MAX_ATTEMPTS` times.

BATCH READING (`BOOKS_BATCH_READS`)
    The vision reads go through OpenAI's Batch API, which answers within 24 hours,
    so a chapter with scanned pages takes two passes:

      SUBMIT   claim, split, upload the pages that need vision as batch jobs, then
               PARK the chapter in `reading` with the batch ids and release the
               claim. A digitally typeset PDF has no such pages and runs straight
               through, as before.
      COLLECT  every pass checks `reading` chapters (at most once a minute each,
               without a claim); one whose batches all finished is claimed from
               `reading` like a queued one, the readings are downloaded and the
               normal pipeline runs with them. Pages a batch did not answer are
               read live, so an expired batch costs money, not the chapter.

    The batch ids stay on the row until the run is saved or fails, so a worker
    that dies while collecting leaves them for the stale re-claim. They are
    deleted at OpenAI only after that.

BATCH EMBEDDING (`BOOKS_BATCH_EMBEDDINGS`)
    The chunk vectors go through the Batch API too, but nothing waits on them:

      SUBMIT   after the pipeline, before SAVE: one request per chunk, keyed by the
               chunk id the row is then saved with. The chapter is saved READY or
               NEEDS_REVIEW as usual, its chunks' `embedding` NULL and the batch
               ids in `embed_batch`. Teachers see pages and report at once; search
               skips the chunks. If the submit itself fails, the run embeds live.
      COLLECT  every pass checks chapters with an `embed_batch` (at most once a
               minute each). Once finished, the vectors are downloaded, chunks the
               batch did not answer are embedded live, and everything is written
               under the chapter lock -- only if `embed_batch` still names these
               batches. A re-run in between replaced the chunks and the batch; its
               SAVE deletes the old batch at OpenAI instead.

    A chapter deleted while its batch runs leaves that batch to finish at OpenAI
    (a fraction of a cent) and its files to OpenAI's retention.

CONTEXTVARS
    Same dance as `whatsapp/jobs.py`: `session_scope` binds the RLS GUCs, but the
    repositories read the campus from a ContextVar.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from openai import OpenAIError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.storage import LocalFileStorage, get_storage
from app.core.config import get_settings
from app.core.context import (
    get_organization_id,
    get_school_id,
    set_organization_id,
    set_school_id,
)
from app.core.logging import get_logger
from app.db.session import session_scope
from app.modules.academics.models import SchoolClass
from app.modules.books.agent import (
    BatchClient,
    BatchEmbedder,
    BatchReader,
    BookAgent,
    BookContext,
    ChapterRef,
    EmbedRequest,
    OpenAIBookAgent,
)
from app.modules.books.models import (
    Book,
    BookChapter,
    BookChapterFile,
    BookChunk,
    BookPage,
    ChapterStatus,
    FileKind,
)
from app.modules.books.pipeline import PipelineResult, SourceFile, pages_to_read, run_pipeline
from app.modules.books.repository import PageRepository
from app.modules.books.service import chapter_prefix

logger = get_logger(__name__)

STALE_AFTER = timedelta(minutes=30)
MAX_ATTEMPTS = 3
BATCH_POLL_SECONDS = 60.0
"""How often one `reading` chapter's batches are checked. `--watch` passes run every
10 s; a batch takes hours, so checking each pass would only spend API calls."""

_last_batch_check: dict[UUID, float] = {}
_last_embed_check: dict[UUID, float] = {}

AgentFactory = Callable[[], BookAgent]


def default_agent_factory() -> BookAgent:
    return OpenAIBookAgent(get_settings())


@contextmanager
def _tenant(organization_id: UUID, school_id: UUID) -> Iterator[None]:
    previous_org, previous_school = get_organization_id(), get_school_id()
    set_organization_id(organization_id)
    set_school_id(school_id)
    try:
        yield
    finally:
        set_school_id(previous_school)
        set_organization_id(previous_org)


@dataclass(frozen=True, slots=True)
class _FileRef:
    id: UUID
    kind: FileKind
    sort_order: int
    storage_key: str


@dataclass(frozen=True, slots=True)
class _Claim:
    chapter_id: UUID
    organization_id: UUID
    school_id: UUID
    locked_at: datetime
    prefix: str
    context: BookContext
    files: tuple[_FileRef, ...]
    read_batch_ids: tuple[str, ...]
    """Batches to collect instead of reading live; empty when none were submitted."""


async def pending_chapters(limit: int) -> list[tuple[UUID, UUID, UUID]]:
    """(chapter, organization, school) for queued and stale chapters, oldest first.

    One platform-admin READ across tenants (RLS `USING` allows it); every write
    afterwards binds the chapter's own organization.
    """
    stale = datetime.now(UTC) - STALE_AFTER
    async with session_scope(None, platform_admin=True) as session:
        rows = await session.execute(
            select(BookChapter.id, BookChapter.organization_id, BookChapter.school_id)
            .where(
                or_(
                    BookChapter.status == ChapterStatus.QUEUED,
                    (BookChapter.status == ChapterStatus.PROCESSING)
                    & (BookChapter.locked_at < stale),
                )
            )
            .order_by(BookChapter.updated_at)
            .limit(limit)
        )
        return [(r[0], r[1], r[2]) for r in rows.all()]


async def reading_chapters() -> list[tuple[UUID, UUID, UUID, list[str]]]:
    """(chapter, organization, school, batch ids) for every chapter in `reading`."""
    async with session_scope(None, platform_admin=True) as session:
        rows = await session.execute(
            select(
                BookChapter.id,
                BookChapter.organization_id,
                BookChapter.school_id,
                BookChapter.read_batch,
            )
            .where(BookChapter.status == ChapterStatus.READING)
            .order_by(BookChapter.updated_at)
        )
        return [(r[0], r[1], r[2], _batch_ids(r[3])) for r in rows.all()]


async def finished_reading_chapters(
    agent_factory: AgentFactory, *, force: bool = False
) -> list[tuple[UUID, UUID, UUID]]:
    """`reading` chapters whose batches have all finished, ready to be collected.

    Checked without a claim -- a finished batch never becomes unfinished, so the
    answer cannot go stale before `process_chapter` claims the row.
    """
    now = time.monotonic()
    ready: list[tuple[UUID, UUID, UUID]] = []
    for chapter_id, organization_id, school_id, batch_ids in await reading_chapters():
        if not force and now - _last_batch_check.get(chapter_id, -BATCH_POLL_SECONDS) < (
            BATCH_POLL_SECONDS
        ):
            continue
        _last_batch_check[chapter_id] = now
        try:
            agent = agent_factory()
            if not isinstance(agent, BatchReader) or not batch_ids:
                ready.append((chapter_id, organization_id, school_id))  # nothing to wait on
            elif await agent.batches_ready(batch_ids):
                ready.append((chapter_id, organization_id, school_id))
        except Exception:  # an unreachable API delays this chapter, never the worker
            logger.exception("book_batch_check_failed", chapter_id=str(chapter_id))
    return ready


async def embedding_chapters() -> list[tuple[UUID, UUID, UUID, list[str]]]:
    """(chapter, organization, school, batch ids) for chapters waiting on vectors."""
    async with session_scope(None, platform_admin=True) as session:
        rows = await session.execute(
            select(
                BookChapter.id,
                BookChapter.organization_id,
                BookChapter.school_id,
                BookChapter.embed_batch,
            )
            .where(BookChapter.embed_batch.is_not(None))
            .order_by(BookChapter.updated_at)
        )
        return [(r[0], r[1], r[2], _batch_ids(r[3])) for r in rows.all()]


async def collect_embeddings(agent_factory: AgentFactory, *, force: bool = False) -> int:
    """Write the vectors of every finished embedding batch. Returns chapters indexed.

    An agent that cannot read batches (the setting was switched off, a test fake)
    embeds the waiting chunks live -- nothing is left waiting on a batch no one
    will ever collect.
    """
    now = time.monotonic()
    indexed = 0
    for chapter_id, organization_id, school_id, batch_ids in await embedding_chapters():
        if not force and now - _last_embed_check.get(chapter_id, -BATCH_POLL_SECONDS) < (
            BATCH_POLL_SECONDS
        ):
            continue
        _last_embed_check[chapter_id] = now
        try:
            agent = agent_factory()
            vectors: dict[str, list[float]] = {}
            if isinstance(agent, BatchEmbedder) and batch_ids:
                if not await agent.batches_ready(batch_ids):
                    continue
                vectors = await agent.collect_embeddings(batch_ids)
            if await _fill_embeddings(
                chapter_id, organization_id, school_id, batch_ids, vectors, agent
            ):
                indexed += 1
                _last_embed_check.pop(chapter_id, None)
                await _discard_batches(agent, batch_ids)
        except Exception:  # an unreachable API delays this chapter, never the worker
            logger.exception("book_embedding_collect_failed", chapter_id=str(chapter_id))
    return indexed


async def _fill_embeddings(
    chapter_id: UUID,
    organization_id: UUID,
    school_id: UUID,
    batch_ids: Sequence[str],
    vectors: dict[str, list[float]],
    agent: BookAgent,
) -> bool:
    """Store a batch's vectors, embedding live what it did not answer. False if the
    chapter no longer waits on these batches (deleted, or re-run since)."""
    with _tenant(organization_id, school_id):
        async with session_scope(organization_id, school_id=school_id) as session:
            waiting = (
                await session.execute(
                    select(BookChunk.id, BookChunk.content).where(
                        BookChunk.chapter_id == chapter_id, BookChunk.embedding.is_(None)
                    )
                )
            ).all()
        # Live calls happen outside any transaction, like the rest of the worker.
        missing = [
            (chunk_id, content) for chunk_id, content in waiting if str(chunk_id) not in vectors
        ]
        live = await agent.embed([content for _, content in missing]) if missing else []
        filled = {
            **{
                chunk_id: vectors[str(chunk_id)]
                for chunk_id, _ in waiting
                if str(chunk_id) in vectors
            },
            **{chunk_id: vector for (chunk_id, _), vector in zip(missing, live, strict=True)},
        }

        async with session_scope(organization_id, school_id=school_id) as session:
            chapter = (
                await session.execute(
                    select(BookChapter).where(BookChapter.id == chapter_id).with_for_update()
                )
            ).scalar_one_or_none()
            if chapter is None or _batch_ids(chapter.embed_batch) != list(batch_ids):
                return False
            for chunk_id, vector in filled.items():
                # `embedding IS NULL`: a chunk replaced meanwhile is simply gone.
                await session.execute(
                    update(BookChunk)
                    .where(BookChunk.id == chunk_id, BookChunk.embedding.is_(None))
                    .values(embedding=vector)
                )
            chapter.embed_batch = None
            chapter.input_tokens += agent.usage.input_tokens
            if chapter.report is not None:
                report = dict(chapter.report)
                calls = dict(report.get("calls") or {})
                for kind, count in agent.usage.calls.items():
                    calls[kind] = calls.get(kind, 0) + count
                report["calls"] = calls
                report["input_tokens"] = report.get("input_tokens", 0) + agent.usage.input_tokens
                report["batch_embedded_chunks"] = len(filled) - len(missing)
                report["batch_embed_fallback_chunks"] = len(missing)
                chapter.report = report  # reassigned: JSONB does not track in-place edits
    logger.info(
        "book_chapter_indexed",
        chapter_id=str(chapter_id),
        from_batch=len(filled) - len(missing),
        live=len(missing),
    )
    return True


async def process_pending(
    *,
    limit: int,
    agent_factory: AgentFactory = default_agent_factory,
    storage: LocalFileStorage | None = None,
    force_batch_check: bool = False,
) -> dict[str, int]:
    """Collect finished batches, then process up to `limit` queued chapters, one
    after another. Returns status counts, plus `indexed` for chapters whose
    embedding batch was collected."""
    counts: dict[str, int] = {}
    indexed = await collect_embeddings(agent_factory, force=force_batch_check)
    if indexed:
        counts["indexed"] = indexed
    collect = await finished_reading_chapters(agent_factory, force=force_batch_check)
    for chapter_id, organization_id, school_id in [
        *collect,
        *await pending_chapters(limit),
    ]:
        status = await process_chapter(
            chapter_id,
            organization_id,
            school_id,
            agent_factory=agent_factory,
            storage=storage,
        )
        if status is not None:
            counts[status.value] = counts.get(status.value, 0) + 1
    return counts


async def process_chapter(
    chapter_id: UUID,
    organization_id: UUID,
    school_id: UUID,
    *,
    agent_factory: AgentFactory = default_agent_factory,
    storage: LocalFileStorage | None = None,
) -> ChapterStatus | None:
    """Run the agent on one chapter. None if someone else holds or finished it.

    READING when its pages were just handed to the Batch API; the chapter comes
    back through `finished_reading_chapters` once the batch is done.
    """
    storage = storage or get_storage()
    claim = await _claim(chapter_id, organization_id, school_id)
    if claim is None:
        return None
    _last_batch_check.pop(chapter_id, None)
    logger.info("book_chapter_processing", chapter_id=str(chapter_id), files=len(claim.files))
    agent: BookAgent | None = None
    embed_ids: list[str] = []
    try:
        agent = agent_factory()
        sources = [
            SourceFile(f.id, f.kind, f.sort_order, await storage.get(f.storage_key))
            for f in claim.files
        ]
        readings = None
        if claim.read_batch_ids:
            if not isinstance(agent, BatchReader):
                raise RuntimeError("This chapter waits on a batch, but the agent cannot read one.")
            readings = await agent.collect_reads(claim.read_batch_ids)
        elif get_settings().BOOKS_BATCH_READS and isinstance(agent, BatchReader):
            requests = await pages_to_read(sources)
            if requests:
                batch_ids = await agent.submit_reads(requests, label=str(chapter_id))
                if not await _park(claim, batch_ids, len(requests)):
                    await agent.discard_batches(batch_ids)
                    return None
                logger.info(
                    "book_chapter_batch_submitted",
                    chapter_id=str(chapter_id),
                    pages=len(requests),
                    batches=len(batch_ids),
                )
                return ChapterStatus.READING
        batch_embed = get_settings().BOOKS_BATCH_EMBEDDINGS and isinstance(agent, BatchEmbedder)
        result = await run_pipeline(claim.context, sources, agent, readings, embed=not batch_embed)
        chunk_ids = [uuid4() for _ in result.chunks]
        if batch_embed and result.chunks:
            embed_ids = await _submit_embeddings(agent, claim, result, chunk_ids)
        page_ids = await _store_images(claim, result, storage)
        replaced = await _save(claim, result, page_ids, chunk_ids, embed_ids, agent, storage)
    except Exception as exc:  # any failure fails THIS chapter, never the worker
        logger.exception("book_chapter_failed", chapter_id=str(chapter_id))
        await _discard_batches(agent, embed_ids)  # its chunks were never saved
        if await _fail(claim, describe_failure(exc)):
            await _discard_batches(agent, claim.read_batch_ids)
        return ChapterStatus.FAILED
    if replaced is None:
        logger.info("book_chapter_result_discarded", chapter_id=str(chapter_id))
        await storage.delete_prefix(_run_folder(claim))
        await _discard_batches(agent, embed_ids)
        return None
    await _discard_batches(agent, [*claim.read_batch_ids, *replaced])
    logger.info(
        "book_chapter_processed",
        chapter_id=str(chapter_id),
        status=result.status.value,
        pages=len(result.pages),
        chunks=len(result.chunks),
        embedding_batches=len(embed_ids),
        issues=len(result.report["issues"]),
    )
    return result.status


async def _submit_embeddings(
    agent: BookAgent, claim: _Claim, result: PipelineResult, chunk_ids: list[UUID]
) -> list[str]:
    """Hand the chunks to an embedding batch; their ids become the saved rows' ids.

    A failed submit embeds the chunks live instead: the pages are already read
    (and paid for), and the vectors cost a fraction of a cent either way.
    """
    if not isinstance(agent, BatchEmbedder):
        raise TypeError("This agent cannot embed through the Batch API.")
    try:
        return await agent.submit_embeddings(
            [
                EmbedRequest(str(i), c.content)
                for i, c in zip(chunk_ids, result.chunks, strict=True)
            ],
            label=f"{claim.chapter_id}-embed",
        )
    except OpenAIError:
        logger.warning("book_embedding_batch_submit_failed", chapter_id=str(claim.chapter_id))
        vectors = await agent.embed([c.content for c in result.chunks])
        result.chunks = [
            replace(c, embedding=v) for c, v in zip(result.chunks, vectors, strict=True)
        ]
        return []


# -- 1. claim ------------------------------------------------------------------


async def _claim(chapter_id: UUID, organization_id: UUID, school_id: UUID) -> _Claim | None:
    stale = datetime.now(UTC) - STALE_AFTER
    with _tenant(organization_id, school_id):
        async with session_scope(organization_id, school_id=school_id) as session:
            chapter = (
                await session.execute(
                    select(BookChapter)
                    .where(BookChapter.id == chapter_id)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if chapter is None:
                return None
            # READING is claimed only after `finished_reading_chapters` saw its
            # batches done; the claim itself does not look at OpenAI.
            claimable = chapter.status in (ChapterStatus.QUEUED, ChapterStatus.READING) or (
                chapter.status is ChapterStatus.PROCESSING
                and chapter.locked_at is not None
                and chapter.locked_at < stale
            )
            if not claimable:
                return None
            if chapter.status is ChapterStatus.PROCESSING and chapter.attempts >= MAX_ATTEMPTS:
                chapter.status = ChapterStatus.FAILED
                chapter.error = (
                    f"Processing stopped responding {MAX_ATTEMPTS} times. "
                    "Check the files and run the agent again."
                )
                chapter.locked_at = None
                return None

            book = (
                await session.execute(select(Book).where(Book.id == chapter.book_id))
            ).scalar_one()
            class_name = (
                await session.execute(
                    select(SchoolClass.name).where(SchoolClass.id == book.class_id)
                )
            ).scalar_one_or_none() or "the class"
            siblings = (
                await session.execute(
                    select(BookChapter.number, BookChapter.title)
                    .where(BookChapter.book_id == book.id)
                    .order_by(BookChapter.number)
                )
            ).all()
            files = (
                (
                    await session.execute(
                        select(BookChapterFile)
                        .where(BookChapterFile.chapter_id == chapter.id)
                        .order_by(BookChapterFile.sort_order)
                    )
                )
                .scalars()
                .all()
            )
            if not files:
                chapter.status = ChapterStatus.EMPTY
                return None

            locked_at = datetime.now(UTC)
            if chapter.status is not ChapterStatus.READING:
                chapter.attempts += 1  # collecting a batch is the same attempt that sent it
            chapter.status = ChapterStatus.PROCESSING
            chapter.locked_at = locked_at
            chapter.error = None

            return _Claim(
                chapter_id=chapter.id,
                organization_id=organization_id,
                school_id=school_id,
                locked_at=locked_at,
                prefix=chapter_prefix(book, chapter.id),
                context=BookContext(
                    title=book.title,
                    class_name=class_name,
                    publisher=book.publisher,
                    version=book.version,
                    chapters=tuple(ChapterRef(n, t) for n, t in siblings),
                    declared=ChapterRef(chapter.number, chapter.title),
                ),
                files=tuple(_FileRef(f.id, f.kind, f.sort_order, f.storage_key) for f in files),
                read_batch_ids=tuple(_batch_ids(chapter.read_batch)),
            )


def _batch_ids(read_batch: dict[str, Any] | None) -> list[str]:
    return [str(i) for i in (read_batch or {}).get("batch_ids", [])]


async def _discard_batches(agent: object, batch_ids: Sequence[str]) -> None:
    """Delete a finished run's batch files at OpenAI -- only once nothing can need them."""
    if batch_ids and isinstance(agent, BatchClient):
        await agent.discard_batches(batch_ids)


# -- 1b. park (batch submitted) --------------------------------------------------


async def _park(claim: _Claim, batch_ids: Sequence[str], pages: int) -> bool:
    """Release the claim with the chapter in READING. False if it is no longer ours."""
    with _tenant(claim.organization_id, claim.school_id):
        async with session_scope(claim.organization_id, school_id=claim.school_id) as session:
            chapter = await _still_ours(session, claim)
            if chapter is None:
                return False
            chapter.status = ChapterStatus.READING
            chapter.read_batch = {
                "batch_ids": list(batch_ids),
                "pages": pages,
                "submitted_at": datetime.now(UTC).isoformat(),
            }
            chapter.locked_at = None
            return True


# -- 2. work (images) ------------------------------------------------------------


async def _store_images(
    claim: _Claim, result: PipelineResult, storage: LocalFileStorage
) -> dict[str, tuple[UUID, str]]:
    """Write each page image under a run-specific folder; (page id, key) by label.

    Run-specific (`pages/<claim time>/`) so a discarded run never overwrites the
    images of the run that won; `_save` removes every older run folder.
    """
    run = _run_folder(claim)
    ids: dict[str, tuple[UUID, str]] = {}
    for page in result.pages:
        page_id = uuid4()
        extension = "png" if page.image_type == "image/png" else "jpg"
        key = f"{run}/{page_id}.{extension}"
        await storage.put(key, page.image)
        ids[page.label] = (page_id, key)
    return ids


# -- 3. save -------------------------------------------------------------------


async def _save(
    claim: _Claim,
    result: PipelineResult,
    page_ids: dict[str, tuple[UUID, str]],
    chunk_ids: list[UUID],
    embed_ids: list[str],
    agent: BookAgent,
    storage: LocalFileStorage,
) -> list[str] | None:
    """Write the run. None if the chapter is no longer ours; else the ids of an
    earlier embedding batch this run's chunks replace, for the caller to delete."""
    with _tenant(claim.organization_id, claim.school_id):
        async with session_scope(claim.organization_id, school_id=claim.school_id) as session:
            chapter = await _still_ours(session, claim)
            if chapter is None:
                return None

            await PageRepository(session).clear_chapter(chapter.id)
            await session.flush()
            for page in result.pages:
                page_id, key = page_ids[page.label]
                session.add(
                    BookPage(
                        id=page_id,
                        chapter_id=chapter.id,
                        file_id=page.file_id,
                        source_index=page.source_index,
                        position=page.position,
                        printed_page_number=page.printed_page_number,
                        placement=page.placement,
                        method=page.method,
                        text=page.text,
                        image_key=key,
                        detected_chapter_number=page.detected_chapter_number,
                        chapter_confidence=page.chapter_confidence,
                        opens_chapter=page.opens_chapter,
                        organization_id=claim.organization_id,
                        school_id=claim.school_id,
                    )
                )
            for chunk, chunk_id in zip(result.chunks, chunk_ids, strict=True):
                session.add(
                    BookChunk(
                        id=chunk_id,
                        book_id=chapter.book_id,
                        chapter_id=chapter.id,
                        chunk_index=chunk.index,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        printed_start=chunk.printed_start,
                        printed_end=chunk.printed_end,
                        content=chunk.content,
                        embedding=chunk.embedding or None,
                        embedding_model=agent.models.get("embed", "unknown"),
                        organization_id=claim.organization_id,
                        school_id=claim.school_id,
                    )
                )
            chapter.status = result.status
            chapter.report = result.report
            chapter.page_count = len(result.pages)
            chapter.processed_at = datetime.now(UTC)
            chapter.locked_at = None
            chapter.error = None
            chapter.input_tokens += agent.usage.input_tokens
            chapter.output_tokens += agent.usage.output_tokens
            chapter.read_batch = None
            replaced = _batch_ids(chapter.embed_batch)
            chapter.embed_batch = (
                {
                    "batch_ids": embed_ids,
                    "chunks": len(chunk_ids),
                    "submitted_at": datetime.now(UTC).isoformat(),
                }
                if embed_ids
                else None
            )

    current = _run_folder(claim).rsplit("/", 1)[1]
    for old in _older_runs(storage, claim.prefix, current):
        await storage.delete_prefix(f"{claim.prefix}/pages/{old}")
    return replaced


def _run_folder(claim: _Claim) -> str:
    return f"{claim.prefix}/pages/{int(claim.locked_at.timestamp() * 1_000_000)}"


def _older_runs(storage: LocalFileStorage, prefix: str, current: str) -> list[str]:
    root = storage.path(f"{prefix}/pages")
    if not root.is_dir():
        return []
    return [p.name for p in root.iterdir() if p.is_dir() and p.name != current]


async def _fail(claim: _Claim, message: str) -> bool:
    """Mark the chapter failed. False if it is no longer ours to fail."""
    with _tenant(claim.organization_id, claim.school_id):
        async with session_scope(claim.organization_id, school_id=claim.school_id) as session:
            chapter = await _still_ours(session, claim)
            if chapter is None:
                return False
            chapter.status = ChapterStatus.FAILED
            chapter.error = message[:1000]
            chapter.locked_at = None
            chapter.read_batch = None
            return True


async def _still_ours(session: AsyncSession, claim: _Claim) -> BookChapter | None:
    chapter = (
        await session.execute(
            select(BookChapter).where(BookChapter.id == claim.chapter_id).with_for_update()
        )
    ).scalar_one_or_none()
    if (
        chapter is None
        or chapter.status is not ChapterStatus.PROCESSING
        or chapter.locked_at != claim.locked_at
    ):
        return None
    return chapter


def describe_failure(exc: Exception) -> str:
    """A message a teacher can act on, without leaking a stack trace."""
    from openai import APIStatusError, AuthenticationError, PermissionDeniedError, RateLimitError

    from app.modules.books.agent import AgentNotConfiguredError
    from app.modules.books.ingest import UnsupportedFileError

    if isinstance(exc, AgentNotConfiguredError):
        return "The AI agent is not configured on this server (OPENAI_API_KEY is missing)."
    if isinstance(exc, AuthenticationError):
        return "OpenAI rejected the server's API key."
    if isinstance(exc, PermissionDeniedError):
        return f"OpenAI refused the request: {exc.message}"
    if isinstance(exc, RateLimitError):
        return "OpenAI's rate limit or quota was reached. Run the agent again later."
    if isinstance(exc, APIStatusError):
        return f"OpenAI returned an error ({exc.status_code}): {exc.message}"
    if isinstance(exc, UnsupportedFileError | ValueError):
        return str(exc)
    return f"The agent failed: {type(exc).__name__}: {exc}"
