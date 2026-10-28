"""Test paper and question bank HTTP endpoints.

AUTHORISATION SHAPE
    paper:read     see papers and the question bank
    paper:write    generate papers and change the ones you created
    paper:manage   change or delete any paper

    Every route is guarded on `paper:read`; writes then check `write` OR `manage`
    in the service, for the reason `books/router.py` gives.

GENERATION IS ASYNCHRONOUS
    `POST /papers` answers 201 with the paper `queued`; poll `GET /papers/{id}`
    until it is `ready`, `needs_review` or `failed`. With
    `PAPERS_INLINE_GENERATION` the API process generates it right after the
    response; otherwise the `process-books` worker does.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from openai import OpenAIError
from sqlalchemy import select

from app.api.deps import AuthContext, DbSession, Pagination, SearchQuery, SettingsDep, require
from app.common.schemas import Page
from app.core.config import Settings
from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.modules.academics.teaching_scope import assigned_teacher
from app.modules.books.agent import AgentNotConfiguredError
from app.modules.books.jobs import describe_failure
from app.modules.papers.generator import PaperAgent
from app.modules.papers.jobs import PaperAgentFactory, default_paper_agent_factory, process_paper
from app.modules.papers.models import (
    Difficulty,
    Paper,
    PaperLanguage,
    PaperStatus,
    QuestionType,
)
from app.modules.papers.schemas import (
    PaperCreate,
    PaperDetail,
    PaperQuestionAdd,
    PaperQuestionRead,
    PaperRead,
    PaperUpdate,
    QuestionRead,
    QuestionUpdate,
    ReplaceRequest,
)
from app.modules.papers.service import Caller, PaperService

router = APIRouter()

ReadCtx = Annotated[AuthContext, Depends(require("paper:read"))]


def get_paper_agent_factory() -> PaperAgentFactory:
    """Overridden in tests with a deterministic fake agent."""
    return default_paper_agent_factory


AgentFactoryDep = Annotated[PaperAgentFactory, Depends(get_paper_agent_factory)]


def _caller(ctx: AuthContext) -> Caller:
    may_manage = ctx.has("paper:manage")
    return Caller(
        user_id=ctx.user_id,
        may_write=ctx.has("paper:write"),
        may_manage=may_manage,
        teacher_id=None if may_manage else assigned_teacher(ctx.user_id, ctx.permissions),
    )


def _service(db: DbSession, settings: Settings) -> PaperService:
    return PaperService(db, settings)


def _live_agent(agent_factory: PaperAgentFactory) -> PaperAgent:
    try:
        return agent_factory()
    except AgentNotConfiguredError as exc:
        raise ServiceUnavailableError(str(exc), code="AI_NOT_CONFIGURED") from exc


async def _after_queue(
    db: DbSession,
    paper: PaperDetail,
    ctx: AuthContext,
    settings: Settings,
    background: BackgroundTasks,
    agent_factory: PaperAgentFactory,
) -> None:
    """With inline generation on, write the paper in this process after the response.

    Commits first, for the reason `books/router.py::_after_queue` gives -- and reads
    the paper's campus before that commit, because the tenant binding is
    transaction-local and nothing can be read through `db` afterwards.
    """
    if not settings.PAPERS_INLINE_GENERATION or paper.status is not PaperStatus.QUEUED:
        return
    school_id = (
        await db.execute(select(Paper.school_id).where(Paper.id == paper.id))
    ).scalar_one_or_none()
    if school_id is None:
        raise NotFoundError("Paper not found.")
    await db.commit()
    background.add_task(
        process_paper, paper.id, ctx.organization_id, school_id, agent_factory=agent_factory
    )


# -- papers ------------------------------------------------------------------


@router.get("", response_model=Page[PaperRead], summary="Test papers on the campus")
async def list_papers(
    db: DbSession,
    ctx: ReadCtx,
    settings: SettingsDep,
    params: Pagination,
    search: SearchQuery,
    class_id: UUID | None = None,
    subject_id: UUID | None = None,
    status_filter: Annotated[PaperStatus | None, Query(alias="status")] = None,
) -> Page[PaperRead]:
    """One page of the campus's papers, newest first.

    `class_id`, `subject_id`, `status` and `q` (title) narrow the list in the
    database, and the page is an offset into the filtered result.
    """
    return await _service(db, settings).list_papers(
        _caller(ctx),
        class_id=class_id,
        subject_id=subject_id,
        status=status_filter,
        params=params,
        search=search,
    )


@router.post(
    "",
    response_model=PaperDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a test paper from a book's chapters",
)
async def create_paper(
    payload: PaperCreate,
    db: DbSession,
    ctx: ReadCtx,
    settings: SettingsDep,
    background: BackgroundTasks,
    agent_factory: AgentFactoryDep,
) -> PaperDetail:
    """Queues the paper. 422 `CHAPTER_NOT_READY` if a chapter has not been read."""
    paper = await _service(db, settings).create(payload, _caller(ctx))
    await _after_queue(db, paper, ctx, settings, background, agent_factory)
    return paper


# Declared before `/{paper_id}`: "questions" is not a paper id.
@router.get(
    "/questions",
    response_model=Page[QuestionRead],
    summary="The question bank",
)
async def question_bank(
    db: DbSession,
    ctx: ReadCtx,
    settings: SettingsDep,
    params: Pagination,
    class_id: UUID | None = None,
    subject_id: UUID | None = None,
    book_id: UUID | None = None,
    chapter_id: UUID | None = None,
    question_type: Annotated[QuestionType | None, Query(alias="type")] = None,
    difficulty: Difficulty | None = None,
    language: PaperLanguage | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[QuestionRead]:
    return await _service(db, settings).question_bank(
        _caller(ctx),
        class_id=class_id,
        subject_id=subject_id,
        book_id=book_id,
        chapter_id=chapter_id,
        qtype=question_type,
        difficulty=difficulty,
        language=language,
        text=q.strip() if q else None,
        params=params,
    )


@router.get("/{paper_id}", response_model=PaperDetail, summary="One paper with its questions")
async def get_paper(
    paper_id: UUID, db: DbSession, ctx: ReadCtx, settings: SettingsDep
) -> PaperDetail:
    return await _service(db, settings).detail(paper_id, _caller(ctx))


@router.patch("/{paper_id}", response_model=PaperDetail, summary="Edit a paper's details")
async def update_paper(
    paper_id: UUID, payload: PaperUpdate, db: DbSession, ctx: ReadCtx, settings: SettingsDep
) -> PaperDetail:
    return await _service(db, settings).update(paper_id, payload, _caller(ctx))


@router.delete(
    "/{paper_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a paper (its questions stay in the bank)",
)
async def delete_paper(
    paper_id: UUID, db: DbSession, ctx: ReadCtx, settings: SettingsDep
) -> Response:
    await _service(db, settings).delete(paper_id, _caller(ctx))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{paper_id}/regenerate",
    response_model=PaperDetail,
    summary="Write the paper again from scratch",
)
async def regenerate_paper(
    paper_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    settings: SettingsDep,
    background: BackgroundTasks,
    agent_factory: AgentFactoryDep,
) -> PaperDetail:
    paper = await _service(db, settings).regenerate(paper_id, _caller(ctx))
    await _after_queue(db, paper, ctx, settings, background, agent_factory)
    return paper


# -- a paper's questions -----------------------------------------------------


@router.post(
    "/{paper_id}/questions",
    response_model=PaperQuestionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a question from the bank",
)
async def add_question(
    paper_id: UUID,
    payload: PaperQuestionAdd,
    db: DbSession,
    ctx: ReadCtx,
    settings: SettingsDep,
) -> PaperQuestionRead:
    return await _service(db, settings).add_entry(paper_id, payload, _caller(ctx))


@router.patch(
    "/{paper_id}/questions/{entry_id}",
    response_model=PaperQuestionRead,
    summary="Edit a question on the paper",
)
async def edit_question(
    paper_id: UUID,
    entry_id: UUID,
    payload: QuestionUpdate,
    db: DbSession,
    ctx: ReadCtx,
    settings: SettingsDep,
) -> PaperQuestionRead:
    """A question other papers also use is copied, so they do not change."""
    return await _service(db, settings).edit_entry(paper_id, entry_id, payload, _caller(ctx))


@router.delete(
    "/{paper_id}/questions/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a question from the paper (it stays in the bank)",
)
async def remove_question(
    paper_id: UUID, entry_id: UUID, db: DbSession, ctx: ReadCtx, settings: SettingsDep
) -> Response:
    await _service(db, settings).remove_entry(paper_id, entry_id, _caller(ctx))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{paper_id}/questions/{entry_id}/replace",
    response_model=PaperQuestionRead,
    summary="Have the AI write a different question for this place",
)
async def replace_question(
    paper_id: UUID,
    entry_id: UUID,
    payload: ReplaceRequest,
    db: DbSession,
    ctx: ReadCtx,
    settings: SettingsDep,
    agent_factory: AgentFactoryDep,
) -> PaperQuestionRead:
    """422 `REPLACEMENT_FAILED` when no new question passed the checks; 503
    `AI_FAILED` when OpenAI refused or failed (the message says which)."""
    agent = _live_agent(agent_factory)
    try:
        return await _service(db, settings).replace_entry(
            paper_id, entry_id, payload, agent, _caller(ctx)
        )
    except OpenAIError as exc:
        raise ServiceUnavailableError(describe_failure(exc), code="AI_FAILED") from exc
