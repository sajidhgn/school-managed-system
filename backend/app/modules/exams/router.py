"""Exam HTTP endpoints -- one line of delegation each.

AUTHORISATION SHAPE
    The already-seeded `grade:read` / `grade:manage` pair, not new codes: the
    catalog seeded them ahead of this module landing (see the note above
    `ACADEMIC_PERMISSIONS`), so teachers can already read AND enter marks and
    every custom role a customer built keeps working on the day exams appear.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthContext, DbSession, Pagination, SearchQuery, Sorting, require
from app.common.schemas import Page
from app.modules.exams.schemas import (
    ExamClassResults,
    ExamCreate,
    ExamPaperCreate,
    ExamPaperRead,
    ExamPaperUpdate,
    ExamRead,
    ExamUpdate,
    MarksUpsert,
    MarksUpsertResult,
    PaperMarksRead,
)
from app.modules.exams.service import ExamService

exams_router = APIRouter()

GradeReadCtx = Annotated[AuthContext, Depends(require("grade:read"))]
GradeManageCtx = Annotated[AuthContext, Depends(require("grade:manage"))]


# ---------------------------------------------------------------------------
# Papers and marks -- declared BEFORE `/{exam_id}` so "papers" is never parsed
# as an exam id (Starlette matches in declaration order).
# ---------------------------------------------------------------------------


@exams_router.get(
    "/papers/{paper_id}/marks",
    response_model=PaperMarksRead,
    summary="The mark sheet for one paper: every student of the class, marks merged in",
)
async def paper_marks(paper_id: UUID, db: DbSession, _ctx: GradeReadCtx) -> PaperMarksRead:
    return await ExamService(db).paper_marks(paper_id)


@exams_router.put(
    "/papers/{paper_id}/marks",
    response_model=MarksUpsertResult,
    summary="Save a paper's mark sheet (upsert; omitted students are untouched)",
)
async def upsert_marks(
    paper_id: UUID, payload: MarksUpsert, db: DbSession, ctx: GradeManageCtx
) -> MarksUpsertResult:
    return await ExamService(db).upsert_marks(paper_id, payload, actor_id=ctx.user_id)


@exams_router.patch(
    "/papers/{paper_id}",
    response_model=ExamPaperRead,
    summary="Change a paper's date or marks scheme",
)
async def update_paper(
    paper_id: UUID, payload: ExamPaperUpdate, db: DbSession, ctx: GradeManageCtx
) -> ExamPaperRead:
    return await ExamService(db).update_paper(paper_id, payload, actor_id=ctx.user_id)


@exams_router.delete(
    "/papers/{paper_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an unmarked paper from its exam",
)
async def remove_paper(paper_id: UUID, db: DbSession, ctx: GradeManageCtx) -> None:
    await ExamService(db).remove_paper(paper_id, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------


@exams_router.get(
    "",
    response_model=Page[ExamRead],
    summary="List and search exams",
)
async def list_exams(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    _ctx: GradeReadCtx,
    search: SearchQuery = None,
) -> Page[ExamRead]:
    return await ExamService(db).list_exams(params, sort, search=search)


@exams_router.post(
    "",
    response_model=ExamRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an exam",
)
async def create_exam(payload: ExamCreate, db: DbSession, ctx: GradeManageCtx) -> ExamRead:
    return await ExamService(db).create_exam(payload, actor_id=ctx.user_id)


@exams_router.get(
    "/{exam_id}",
    response_model=ExamRead,
    summary="Get an exam",
)
async def get_exam(exam_id: UUID, db: DbSession, _ctx: GradeReadCtx) -> ExamRead:
    return await ExamService(db).read_exam(exam_id)


@exams_router.patch(
    "/{exam_id}",
    response_model=ExamRead,
    summary="Edit an exam's name, dates, term or status",
)
async def update_exam(
    exam_id: UUID, payload: ExamUpdate, db: DbSession, ctx: GradeManageCtx
) -> ExamRead:
    return await ExamService(db).update_exam(exam_id, payload, actor_id=ctx.user_id)


@exams_router.delete(
    "/{exam_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an exam no marks have been entered for",
)
async def delete_exam(exam_id: UUID, db: DbSession, ctx: GradeManageCtx) -> None:
    await ExamService(db).delete_exam(exam_id, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Papers of one exam
# ---------------------------------------------------------------------------


@exams_router.get(
    "/{exam_id}/papers",
    response_model=list[ExamPaperRead],
    summary="The papers of an exam, in class-then-subject order",
)
async def list_papers(exam_id: UUID, db: DbSession, _ctx: GradeReadCtx) -> list[ExamPaperRead]:
    return await ExamService(db).list_papers(exam_id)


@exams_router.post(
    "/{exam_id}/papers",
    response_model=ExamPaperRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a paper (one class sitting one subject) to an exam",
)
async def add_paper(
    exam_id: UUID, payload: ExamPaperCreate, db: DbSession, ctx: GradeManageCtx
) -> ExamPaperRead:
    return await ExamService(db).add_paper(exam_id, payload, actor_id=ctx.user_id)


@exams_router.get(
    "/{exam_id}/results",
    response_model=ExamClassResults,
    summary="The result sheet for one class: papers as columns, students ranked",
)
async def class_results(
    exam_id: UUID, class_id: UUID, db: DbSession, _ctx: GradeReadCtx
) -> ExamClassResults:
    return await ExamService(db).class_results(exam_id, class_id)
