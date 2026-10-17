"""Textbook library HTTP endpoints -- one line of delegation each, mostly.

AUTHORISATION SHAPE
    book:read     see books, chapters, pages, files; search a book; search and
                  ask the whole library (within the caller's teaching scope)
    book:write    upload books and change the ones you uploaded
    book:manage   change or delete any book

    Every route is guarded on `book:read`; writes then check `write` OR `manage` in
    the service, because `require()` demands ALL of its codes and a coordinator may
    hold `manage` without `write`.

UPLOADS ARE MULTIPART
    `POST /books/{id}/chapters/{cid}/files` takes `files` (one or many PDFs/images)
    and `process` (default true: queue the agent as soon as the files land).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import AuthContext, DbSession, SettingsDep, require
from app.common.storage import LocalFileStorage, get_storage
from app.core.config import Settings
from app.core.exceptions import NotFoundError, ServiceUnavailableError, ValidationError
from app.modules.academics.teaching_scope import assigned_teacher
from app.modules.books.agent import AgentNotConfiguredError, Answerer, BookAgent
from app.modules.books.jobs import AgentFactory, default_agent_factory, process_chapter
from app.modules.books.models import BookChapter, ChapterStatus
from app.modules.books.repository import LibraryScope
from app.modules.books.schemas import (
    AskRequest,
    BookCreate,
    BookDetail,
    BookRead,
    BookSearchHit,
    BookUpdate,
    ChapterInput,
    ChapterRead,
    ChapterUpdate,
    LibraryAnswer,
    LibraryHit,
    PageRead,
)
from app.modules.books.service import BookService, Caller, IncomingFile

router = APIRouter()

_MAX_REQUEST_MB = 250
"""All files of one upload together -- what one request may hold in memory."""

ReadCtx = Annotated[AuthContext, Depends(require("book:read"))]


def get_book_storage(settings: SettingsDep) -> LocalFileStorage:
    return get_storage(settings)


def get_agent_factory() -> AgentFactory:
    """Overridden in tests with a deterministic fake agent."""
    return default_agent_factory


StorageDep = Annotated[LocalFileStorage, Depends(get_book_storage)]
AgentFactoryDep = Annotated[AgentFactory, Depends(get_agent_factory)]


def _caller(ctx: AuthContext) -> Caller:
    """`book:manage` lifts the teaching-scope bound: "any book" cannot be managed
    through books you cannot see."""
    may_manage = ctx.has("book:manage")
    return Caller(
        user_id=ctx.user_id,
        may_write=ctx.has("book:write"),
        may_manage=may_manage,
        teacher_id=None if may_manage else assigned_teacher(ctx.user_id, ctx.permissions),
    )


def _service(db: DbSession, storage: LocalFileStorage, settings: Settings) -> BookService:
    return BookService(db, storage, settings)


async def _after_queue(
    db: DbSession,
    chapter: ChapterRead,
    ctx: AuthContext,
    settings: Settings,
    storage: LocalFileStorage,
    background: BackgroundTasks,
    agent_factory: AgentFactory,
) -> None:
    """With inline processing on, run the agent in this process after the response.

    Commits first, deliberately: the background run opens its own session and must
    see the chapter as QUEUED, which it cannot until this request's transaction is
    committed.

    NOTHING MAY READ THROUGH `db` AFTER THAT COMMIT. The RLS tenant binding is
    transaction-local (`set_config(..., true)`), so the commit discards it and every
    later query on this session sees zero rows. The chapter's campus is therefore
    read first -- from the row, not from `ctx.school_id`, which is None for an
    org-level principal acting on a campus they selected.
    """
    if not settings.BOOKS_INLINE_PROCESSING or chapter.status is not ChapterStatus.QUEUED:
        return
    school_id = await _chapter_school(chapter.id, db)
    await db.commit()
    background.add_task(
        process_chapter,
        chapter.id,
        ctx.organization_id,
        school_id,
        agent_factory=agent_factory,
        storage=storage,
    )


async def _chapter_school(chapter_id: UUID, db: DbSession) -> UUID:
    school_id = (
        await db.execute(select(BookChapter.school_id).where(BookChapter.id == chapter_id))
    ).scalar_one_or_none()
    if school_id is None:
        raise NotFoundError("Chapter not found.")
    return school_id


# -- books -------------------------------------------------------------------


@router.get("", response_model=list[BookRead], summary="Books on the campus")
async def list_books(
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
    class_id: UUID | None = None,
    subject_id: UUID | None = None,
) -> list[BookRead]:
    return await _service(db, storage, settings).list_books(
        _caller(ctx), class_id=class_id, subject_id=subject_id
    )


def _live_agent(agent_factory: AgentFactory) -> BookAgent:
    try:
        return agent_factory()
    except AgentNotConfiguredError as exc:
        raise ServiceUnavailableError(str(exc), code="AI_NOT_CONFIGURED") from exc


# Declared before `/{book_id}`: "search" and "ask" are not book ids.
@router.get(
    "/search",
    response_model=list[LibraryHit],
    summary="Hybrid (meaning + keyword) search across every book you can see",
)
async def search_library(
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
    agent_factory: AgentFactoryDep,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    class_id: UUID | None = None,
    subject_id: UUID | None = None,
    book_id: UUID | None = None,
    chapter_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> list[LibraryHit]:
    agent = _live_agent(agent_factory)

    async def embed(text: str) -> list[float]:
        return (await agent.embed([text]))[0]

    scope = LibraryScope(
        class_id=class_id,
        subject_id=subject_id,
        book_id=book_id,
        chapter_id=chapter_id,
        teacher_id=_caller(ctx).teacher_id,
    )
    return await _service(db, storage, settings).search_library(q, embed, scope, limit=limit)


@router.post(
    "/ask",
    response_model=LibraryAnswer,
    summary="Ask the library: an answer written from your books, with page citations",
)
async def ask_library(
    payload: AskRequest,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
    agent_factory: AgentFactoryDep,
) -> LibraryAnswer:
    """Narrow it with `class_id`, `subject_id`, `book_id` or `chapter_id`. `found` is
    false when the books do not cover the question -- the model is not allowed to
    answer from its own knowledge."""
    agent = _live_agent(agent_factory)
    if not isinstance(agent, Answerer):
        raise ServiceUnavailableError(
            "The book agent cannot answer questions.", code="AI_NOT_CONFIGURED"
        )

    async def embed(text: str) -> list[float]:
        return (await agent.embed([text]))[0]

    return await _service(db, storage, settings).ask(
        payload, embed, agent, teacher_id=_caller(ctx).teacher_id
    )


@router.post(
    "",
    response_model=BookDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a book: Title, Class, Publisher, Version, and optionally its chapter list",
)
async def create_book(
    payload: BookCreate, db: DbSession, ctx: ReadCtx, storage: StorageDep, settings: SettingsDep
) -> BookDetail:
    """409 `DUPLICATE_BOOK` if the class already has that title/publisher/version."""
    return await _service(db, storage, settings).create(payload, _caller(ctx))


@router.get("/{book_id}", response_model=BookDetail, summary="One book with its chapters")
async def get_book(
    book_id: UUID, db: DbSession, ctx: ReadCtx, storage: StorageDep, settings: SettingsDep
) -> BookDetail:
    return await _service(db, storage, settings).detail(book_id, _caller(ctx))


@router.patch("/{book_id}", response_model=BookDetail, summary="Edit a book's details")
async def update_book(
    book_id: UUID,
    payload: BookUpdate,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> BookDetail:
    return await _service(db, storage, settings).update(book_id, payload, _caller(ctx))


@router.delete(
    "/{book_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a book, its files and its index",
)
async def delete_book(
    book_id: UUID, db: DbSession, ctx: ReadCtx, storage: StorageDep, settings: SettingsDep
) -> Response:
    await _service(db, storage, settings).delete(book_id, _caller(ctx))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- chapters ----------------------------------------------------------------


@router.post(
    "/{book_id}/chapters",
    response_model=ChapterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a chapter to the book's chapter list",
)
async def add_chapter(
    book_id: UUID,
    payload: ChapterInput,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> ChapterRead:
    return await _service(db, storage, settings).add_chapter(book_id, payload, _caller(ctx))


@router.patch(
    "/{book_id}/chapters/{chapter_id}",
    response_model=ChapterRead,
    summary="Renumber or rename a chapter",
)
async def update_chapter(
    book_id: UUID,
    chapter_id: UUID,
    payload: ChapterUpdate,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> ChapterRead:
    return await _service(db, storage, settings).update_chapter(
        book_id, chapter_id, payload, _caller(ctx)
    )


@router.delete(
    "/{book_id}/chapters/{chapter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a chapter with its files and index",
)
async def delete_chapter(
    book_id: UUID,
    chapter_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> Response:
    await _service(db, storage, settings).delete_chapter(book_id, chapter_id, _caller(ctx))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{book_id}/chapters/{chapter_id}/files",
    response_model=ChapterRead,
    summary="Upload a chapter's pages: a PDF, or photos of the pages",
)
async def upload_files(
    book_id: UUID,
    chapter_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
    background: BackgroundTasks,
    agent_factory: AgentFactoryDep,
    files: Annotated[list[UploadFile], File(description="PDF, JPEG, PNG or WebP files.")],
    process: Annotated[bool, Form()] = True,
) -> ChapterRead:
    """Photos may be uploaded in any order -- the agent orders them by printed page
    number. Uploading drops the chapter's previous pages and vectors; with
    `process=true` the agent is queued straight away."""
    limit = settings.BOOKS_MAX_UPLOAD_MB * 1024 * 1024
    # Checked before anything is read: the files are spooled to disk by the
    # multipart parser, but `.read()` below holds each one in memory.
    total = sum(upload.size or 0 for upload in files)
    if total > _MAX_REQUEST_MB * 1024 * 1024:
        raise ValidationError(
            f"Upload at most {_MAX_REQUEST_MB} MB at a time; split the chapter into "
            "several uploads.",
            code="UPLOAD_TOO_LARGE",
        )
    incoming: list[IncomingFile] = []
    for upload in files:
        if upload.size is not None and upload.size > limit:
            raise ValidationError(
                f"{upload.filename} is larger than {settings.BOOKS_MAX_UPLOAD_MB} MB.",
                code="FILE_TOO_LARGE",
            )
        incoming.append(IncomingFile(upload.filename or "upload", await upload.read(limit + 1)))
    chapter = await _service(db, storage, settings).upload(
        book_id, chapter_id, incoming, _caller(ctx), process=process
    )
    await _after_queue(db, chapter, ctx, settings, storage, background, agent_factory)
    return chapter


@router.delete(
    "/{book_id}/chapters/{chapter_id}/files/{file_id}",
    response_model=ChapterRead,
    summary="Remove one uploaded file",
)
async def delete_file(
    book_id: UUID,
    chapter_id: UUID,
    file_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> ChapterRead:
    return await _service(db, storage, settings).delete_file(
        book_id, chapter_id, file_id, _caller(ctx)
    )


@router.get("/{book_id}/files/{file_id}", summary="Download an uploaded file")
async def download_file(
    book_id: UUID,
    file_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> FileResponse:
    path, media_type, name = await _service(db, storage, settings).file_path(
        book_id, file_id, teacher_id=_caller(ctx).teacher_id
    )
    if not path.is_file():
        raise NotFoundError("The file is missing from storage.")
    return FileResponse(
        path, media_type=media_type, filename=name, headers={"Cache-Control": "private"}
    )


@router.post(
    "/{book_id}/chapters/{chapter_id}/process",
    response_model=ChapterRead,
    summary="Queue the agent to (re)read, order, verify and index a chapter",
)
async def process(
    book_id: UUID,
    chapter_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
    background: BackgroundTasks,
    agent_factory: AgentFactoryDep,
) -> ChapterRead:
    chapter = await _service(db, storage, settings).queue(book_id, chapter_id, _caller(ctx))
    await _after_queue(db, chapter, ctx, settings, storage, background, agent_factory)
    return chapter


@router.post(
    "/{book_id}/chapters/{chapter_id}/accept",
    response_model=ChapterRead,
    summary="Accept a chapter the agent flagged for review",
)
async def accept(
    book_id: UUID,
    chapter_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> ChapterRead:
    return await _service(db, storage, settings).accept(book_id, chapter_id, _caller(ctx))


@router.get(
    "/{book_id}/chapters/{chapter_id}/pages",
    response_model=list[PageRead],
    summary="A chapter's pages in the agent's order, with their text",
)
async def list_pages(
    book_id: UUID,
    chapter_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> list[PageRead]:
    return await _service(db, storage, settings).chapter_pages(
        book_id, chapter_id, teacher_id=_caller(ctx).teacher_id
    )


@router.get("/{book_id}/pages/{page_id}/image", summary="A page's image")
async def page_image(
    book_id: UUID,
    page_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
) -> FileResponse:
    path, media_type = await _service(db, storage, settings).page_image(
        book_id, page_id, teacher_id=_caller(ctx).teacher_id
    )
    if not path.is_file():
        raise NotFoundError("The page image is missing from storage.")
    return FileResponse(
        path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"}
    )


@router.get(
    "/{book_id}/search",
    response_model=list[BookSearchHit],
    summary="Semantic search over a book's indexed chapters (pgvector)",
)
async def search(
    book_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    storage: StorageDep,
    settings: SettingsDep,
    agent_factory: AgentFactoryDep,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    chapter_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> list[BookSearchHit]:
    try:
        agent = agent_factory()
    except AgentNotConfiguredError as exc:
        raise ServiceUnavailableError(str(exc), code="AI_NOT_CONFIGURED") from exc

    async def embed(text: str) -> list[float]:
        return (await agent.embed([text]))[0]

    return await _service(db, storage, settings).search(
        book_id, q, embed, chapter_id=chapter_id, limit=limit, teacher_id=_caller(ctx).teacher_id
    )
