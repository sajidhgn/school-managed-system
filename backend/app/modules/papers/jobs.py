"""The paper worker: claim a queued paper, write it, save it.

WHY THIS FILE EXISTS
    Writing and checking a paper takes 20-60 seconds of model calls -- too long
    for a request, so `create` queues the paper and this runs it. It runs in the
    same loop as the book worker (`process-books --watch`), so a deployment needs
    no new container.

CLAIMING, AS FOR BOOK CHAPTERS
    A paper is claimed with `FOR UPDATE SKIP LOCKED`, marked GENERATING with a
    `locked_at` token, and its results are written only if that token is still
    the one this worker set -- a paper deleted or re-queued meanwhile is left
    alone. A run that dies is retried after `STALE_AFTER`, at most `MAX_ATTEMPTS`
    times.

NO DATABASE SESSION IS HELD WHILE THE MODELS WORK
    The claim reads the chapter text and commits; the model calls run with no
    transaction open; the save opens a new one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import (
    get_organization_id,
    get_school_id,
    set_organization_id,
    set_school_id,
)
from app.core.logging import get_logger
from app.db.session import session_scope
from app.modules.books.repository import BookLookupRepository
from app.modules.papers.agent import OpenAIPaperAgent
from app.modules.papers.generator import Generation, PaperAgent, Slot, Source, generate
from app.modules.papers.models import Paper, PaperLanguage, PaperQuestion, PaperStatus
from app.modules.papers.repository import PaperQuestionRepository, SourceRepository
from app.modules.papers.service import build_source, new_question, slots_for

logger = get_logger(__name__)

STALE_AFTER = timedelta(minutes=15)
MAX_ATTEMPTS = 3

PaperAgentFactory = Callable[[], PaperAgent]


def default_paper_agent_factory() -> PaperAgent:
    return OpenAIPaperAgent(get_settings())


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
class _Claim:
    paper_id: UUID
    organization_id: UUID
    school_id: UUID
    locked_at: datetime
    language: PaperLanguage
    source: Source
    chapter_ids: dict[int, UUID]
    slots: tuple[Slot, ...]


async def pending_papers(limit: int) -> list[tuple[UUID, UUID, UUID]]:
    """(paper, organization, school) for queued and stale papers, oldest first."""
    stale = datetime.now(UTC) - STALE_AFTER
    async with session_scope(None, platform_admin=True) as session:
        rows = await session.execute(
            select(Paper.id, Paper.organization_id, Paper.school_id)
            .where(
                or_(
                    Paper.status == PaperStatus.QUEUED,
                    (Paper.status == PaperStatus.GENERATING) & (Paper.locked_at < stale),
                )
            )
            .order_by(Paper.updated_at)
            .limit(limit)
        )
        return [(r[0], r[1], r[2]) for r in rows.all()]


async def process_pending_papers(
    *, limit: int, agent_factory: PaperAgentFactory = default_paper_agent_factory
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper_id, organization_id, school_id in await pending_papers(limit):
        status = await process_paper(
            paper_id, organization_id, school_id, agent_factory=agent_factory
        )
        if status is not None:
            key = f"paper_{status.value}"
            counts[key] = counts.get(key, 0) + 1
    return counts


async def process_paper(
    paper_id: UUID,
    organization_id: UUID,
    school_id: UUID,
    *,
    agent_factory: PaperAgentFactory = default_paper_agent_factory,
) -> PaperStatus | None:
    """Write one paper. None if someone else holds it or it is not queued."""
    try:
        claim = await _claim(paper_id, organization_id, school_id)
    except Exception as exc:  # the chapters cannot be read: fail the paper, not the worker
        logger.exception("paper_claim_failed", paper_id=str(paper_id))
        await _fail_unclaimed(paper_id, organization_id, school_id, _describe(exc))
        return PaperStatus.FAILED
    if claim is None:
        return None
    logger.info("paper_generating", paper_id=str(paper_id), slots=len(claim.slots))
    agent: PaperAgent | None = None
    try:
        agent = agent_factory()
        result = await generate(claim.source, claim.slots, claim.language, agent)
        status = await _save(claim, result, agent)
    except Exception as exc:  # any failure fails THIS paper, never the worker
        logger.exception("paper_failed", paper_id=str(paper_id))
        await _fail(claim, _describe(exc), agent)
        return PaperStatus.FAILED
    if status is None:
        logger.info("paper_result_discarded", paper_id=str(paper_id))
        return None
    logger.info(
        "paper_generated",
        paper_id=str(paper_id),
        status=status.value,
        questions=len(result.chosen),
        issues=len(result.issues),
    )
    return status


async def _claim(paper_id: UUID, organization_id: UUID, school_id: UUID) -> _Claim | None:
    stale = datetime.now(UTC) - STALE_AFTER
    with _tenant(organization_id, school_id):
        async with session_scope(organization_id, school_id=school_id) as session:
            paper = (
                await session.execute(
                    select(Paper).where(Paper.id == paper_id).with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if paper is None:
                return None
            claimable = paper.status is PaperStatus.QUEUED or (
                paper.status is PaperStatus.GENERATING
                and paper.locked_at is not None
                and paper.locked_at < stale
            )
            if not claimable:
                return None
            if paper.status is PaperStatus.GENERATING and paper.attempts >= MAX_ATTEMPTS:
                paper.status = PaperStatus.FAILED
                paper.error = (
                    f"Generation stopped responding {MAX_ATTEMPTS} times. Try again later."
                )
                paper.locked_at = None
                return None

            source, chapter_ids = await build_source(
                SourceRepository(session),
                paper,
                BookLookupRepository(session),
                get_settings().PAPERS_MAX_SOURCE_CHARS,
            )
            locked_at = datetime.now(UTC)
            paper.attempts += 1
            paper.status = PaperStatus.GENERATING
            paper.locked_at = locked_at
            paper.error = None
            return _Claim(
                paper_id=paper.id,
                organization_id=organization_id,
                school_id=school_id,
                locked_at=locked_at,
                language=paper.language,
                source=source,
                chapter_ids=chapter_ids,
                slots=tuple(slots_for(paper)),
            )


async def _save(claim: _Claim, result: Generation, agent: PaperAgent) -> PaperStatus | None:
    with _tenant(claim.organization_id, claim.school_id):
        async with session_scope(claim.organization_id, school_id=claim.school_id) as session:
            paper = await _still_ours(session, claim)
            if paper is None:
                return None
            await PaperQuestionRepository(session).clear(paper.id)
            for position, chosen in enumerate(result.chosen, start=1):
                question = new_question(paper, chosen, claim.chapter_ids, paper.created_by_user_id)
                session.add(question)
                await session.flush()
                session.add(
                    PaperQuestion(
                        organization_id=paper.organization_id,
                        school_id=paper.school_id,
                        paper_id=paper.id,
                        question_id=question.id,
                        position=position,
                        marks=chosen.slot.marks,
                        requested_difficulty=chosen.slot.difficulty,
                    )
                )
            if not result.chosen:
                status = PaperStatus.FAILED
                paper.error = (
                    "No question could be written from these chapters and pass the checks."
                )
            else:
                status = PaperStatus.READY if result.complete else PaperStatus.NEEDS_REVIEW
            paper.status = status
            paper.report = {
                "issues": result.issues,
                "slots": len(claim.slots),
                "written": result.written,
                "passed": result.passed,
                "chosen": len(result.chosen),
                "models": dict(agent.models),
                "calls": dict(agent.usage.calls),
                "input_tokens": agent.usage.input_tokens,
                "output_tokens": agent.usage.output_tokens,
            }
            paper.locked_at = None
            paper.generated_at = datetime.now(UTC)
            paper.input_tokens += agent.usage.input_tokens
            paper.output_tokens += agent.usage.output_tokens
            return status


async def _fail(claim: _Claim, message: str, agent: PaperAgent | None) -> None:
    with _tenant(claim.organization_id, claim.school_id):
        async with session_scope(claim.organization_id, school_id=claim.school_id) as session:
            paper = await _still_ours(session, claim)
            if paper is None:
                return
            paper.status = PaperStatus.FAILED
            paper.error = message[:1000]
            paper.locked_at = None
            if agent is not None:
                paper.input_tokens += agent.usage.input_tokens
                paper.output_tokens += agent.usage.output_tokens


async def _fail_unclaimed(
    paper_id: UUID, organization_id: UUID, school_id: UUID, message: str
) -> None:
    with _tenant(organization_id, school_id):
        async with session_scope(organization_id, school_id=school_id) as session:
            paper = (
                await session.execute(select(Paper).where(Paper.id == paper_id).with_for_update())
            ).scalar_one_or_none()
            if paper is None or paper.status is not PaperStatus.QUEUED:
                return
            paper.status = PaperStatus.FAILED
            paper.error = message[:1000]


async def _still_ours(session: AsyncSession, claim: _Claim) -> Paper | None:
    paper = (
        await session.execute(select(Paper).where(Paper.id == claim.paper_id).with_for_update())
    ).scalar_one_or_none()
    if (
        paper is None
        or paper.status is not PaperStatus.GENERATING
        or paper.locked_at != claim.locked_at
    ):
        return None
    return paper


def _describe(exc: Exception) -> str:
    """A message a teacher can act on, without leaking a stack trace."""
    from app.core.exceptions import ValidationError
    from app.modules.books.jobs import describe_failure

    if isinstance(exc, ValidationError):
        return exc.message
    return describe_failure(exc)
