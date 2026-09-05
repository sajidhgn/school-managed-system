"""Exam business rules.

Everything that decides what is ALLOWED in the gradebook: that an exam name is
unique per school, that a paper's class actually studies its subject is NOT
enforced (schools examine outside the curriculum -- entrance tests, combined
papers), that a mark can only be entered for a student seated in the paper's
class, and that an exam with marks cannot be deleted.

INTERACTIONS
    * `router.py` translates HTTP; this layer never imports fastapi.
    * Reads the academics tables (classes, subjects, terms) as dimensions but
      never writes them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams, SortParams
from app.core.context import require_organization_id, require_school_id
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.models import SchoolClass, Subject
from app.modules.academics.repository import ClassRepository, SubjectRepository, TermRepository
from app.modules.exams.models import Exam, ExamPaper
from app.modules.exams.repository import (
    ExamMarkRepository,
    ExamPaperRepository,
    ExamRepository,
)
from app.modules.exams.schemas import (
    ExamClassResults,
    ExamCreate,
    ExamPaperCreate,
    ExamPaperRead,
    ExamPaperUpdate,
    ExamRead,
    ExamResultRow,
    ExamUpdate,
    MarksUpsert,
    MarksUpsertResult,
    PaperMarksRead,
    ResultCell,
    StudentMarkRow,
)

logger = get_logger(__name__)


class ExamService:
    """Exam, paper and mark lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.exams = ExamRepository(session)
        self.papers = ExamPaperRepository(session)
        self.marks = ExamMarkRepository(session)
        self.classes = ClassRepository(session)
        self.subjects = SubjectRepository(session)
        self.terms = TermRepository(session)

    # -- exams ---------------------------------------------------------------

    async def create_exam(self, payload: ExamCreate, *, actor_id: UUID) -> ExamRead:
        if await self.exams.get_by_name(payload.name):
            raise ConflictError(f"An exam named '{payload.name}' already exists.")
        if payload.term_id is not None and await self.terms.get(payload.term_id) is None:
            raise NotFoundError("Term not found.")

        exam = await self.exams.create(
            **payload.model_dump(),
            organization_id=require_organization_id(),
            school_id=require_school_id(),
        )
        await self._audit(
            AuditAction.EXAM_CREATED,
            entity_type="exam",
            entity_id=exam.id,
            actor_id=actor_id,
            after={"name": exam.name},
        )
        return self._to_exam_read(exam)

    async def list_exams(
        self, params: PageParams, sort: SortParams, *, search: str | None = None
    ) -> Page[ExamRead]:
        conditions = [self.exams.search_filter(search)] if search else []
        rows, total = await self.exams.list(*conditions, params=params, sort=sort)
        counts = await self.exams.paper_counts()
        return Page.create(
            [self._to_exam_read(r, paper_count=counts.get(r.id, 0)) for r in rows],
            total,
            params,
        )

    async def get_exam(self, exam_id: UUID) -> Exam:
        exam = await self.exams.get(exam_id)
        if exam is None:
            raise NotFoundError("Exam not found.")
        return exam

    async def read_exam(self, exam_id: UUID) -> ExamRead:
        exam = await self.get_exam(exam_id)
        counts = await self.exams.paper_counts()
        return self._to_exam_read(exam, paper_count=counts.get(exam.id, 0))

    async def update_exam(self, exam_id: UUID, payload: ExamUpdate, *, actor_id: UUID) -> ExamRead:
        exam = await self.get_exam(exam_id)
        values = payload.model_dump(exclude_unset=True)

        name = values.get("name")
        if name and name != exam.name and await self.exams.get_by_name(name):
            raise ConflictError(f"An exam named '{name}' already exists.")
        if values.get("term_id") is not None and await self.terms.get(values["term_id"]) is None:
            raise NotFoundError("Term not found.")

        start = values.get("start_date", exam.start_date)
        end = values.get("end_date", exam.end_date)
        if start and end and end < start:
            raise ValidationError("end_date must not be before start_date.")

        before = {"name": exam.name, "status": exam.status.value}
        updated = await self.exams.update(exam, **values)
        await self._audit(
            AuditAction.EXAM_UPDATED,
            entity_type="exam",
            entity_id=exam_id,
            actor_id=actor_id,
            before=before,
            after={k: str(v) for k, v in values.items()},
        )
        counts = await self.exams.paper_counts()
        return self._to_exam_read(updated, paper_count=counts.get(exam_id, 0))

    async def delete_exam(self, exam_id: UUID, *, actor_id: UUID) -> None:
        """Soft-delete an exam nobody has marked.

        An exam WITH marks is a term's academic record; deleting it would erase
        every report card built on it. The refusal names the fact rather than
        letting a cascade silently take the marks along.
        """
        exam = await self.get_exam(exam_id)
        if await self.papers.marks_exist(exam_id):
            raise ConflictError(
                f"'{exam.name}' already has marks entered. "
                "Delete is only available before marking begins."
            )
        await self.exams.soft_delete(exam)
        await self._audit(
            AuditAction.EXAM_DELETED,
            entity_type="exam",
            entity_id=exam_id,
            actor_id=actor_id,
            before={"name": exam.name},
        )

    # -- papers --------------------------------------------------------------

    async def list_papers(self, exam_id: UUID) -> list[ExamPaperRead]:
        await self.get_exam(exam_id)  # 404 for unknown or cross-tenant ids
        entered = await self.papers.marks_entered_counts(exam_id)
        return [
            self._to_paper_read(paper, subject, school_class, entered.get(paper.id, 0))
            for paper, subject, school_class in await self.papers.list_for_exam(exam_id)
        ]

    async def add_paper(
        self, exam_id: UUID, payload: ExamPaperCreate, *, actor_id: UUID
    ) -> ExamPaperRead:
        exam = await self.get_exam(exam_id)
        school_class = await self.classes.get(payload.class_id)
        if school_class is None:
            raise NotFoundError("Class not found.")
        subject = await self.subjects.get(payload.subject_id)
        if subject is None:
            raise NotFoundError("Subject not found.")
        if await self.papers.get_paper(exam_id, payload.class_id, payload.subject_id):
            raise ConflictError(
                f"{school_class.name} already sits '{subject.name}' in this exam."
            )

        paper = await self.papers.create(
            **payload.model_dump(),
            exam_id=exam.id,
            organization_id=exam.organization_id,
            school_id=exam.school_id,
        )
        await self._audit(
            AuditAction.EXAM_PAPER_ADDED,
            entity_type="exam_paper",
            entity_id=paper.id,
            actor_id=actor_id,
            after={"exam": exam.name, "class": school_class.name, "subject": subject.code},
        )
        return self._to_paper_read(paper, subject, school_class, 0)

    async def update_paper(
        self, paper_id: UUID, payload: ExamPaperUpdate, *, actor_id: UUID
    ) -> ExamPaperRead:
        paper = await self._get_paper(paper_id)
        values = payload.model_dump(exclude_unset=True)

        max_marks = values.get("max_marks", paper.max_marks)
        pass_marks = values.get("pass_marks", paper.pass_marks)
        if pass_marks is not None and pass_marks > max_marks:
            raise ValidationError("pass_marks cannot exceed max_marks.")

        before = {"max_marks": paper.max_marks, "pass_marks": paper.pass_marks}
        updated = await self.papers.update(paper, **values)
        await self._audit(
            AuditAction.EXAM_PAPER_UPDATED,
            entity_type="exam_paper",
            entity_id=paper_id,
            actor_id=actor_id,
            before=before,
            after={k: str(v) for k, v in values.items()},
        )
        subject = await self.subjects.get(updated.subject_id)
        school_class = await self.classes.get(updated.class_id)
        assert subject is not None and school_class is not None  # FK-guaranteed
        entered = await self.marks.count_for_paper(paper_id)
        return self._to_paper_read(updated, subject, school_class, entered)

    async def remove_paper(self, paper_id: UUID, *, actor_id: UUID) -> None:
        """Remove a paper -- refused once marked, same reasoning as the exam."""
        paper = await self._get_paper(paper_id)
        if await self.marks.count_for_paper(paper_id) > 0:
            raise ConflictError(
                "This paper already has marks entered. "
                "Remove is only available before marking begins."
            )
        await self.papers.soft_delete(paper)
        await self._audit(
            AuditAction.EXAM_PAPER_REMOVED,
            entity_type="exam_paper",
            entity_id=paper_id,
            actor_id=actor_id,
            before={"exam_id": str(paper.exam_id), "subject_id": str(paper.subject_id)},
        )

    # -- marks ---------------------------------------------------------------

    async def paper_marks(self, paper_id: UUID) -> PaperMarksRead:
        """The mark sheet: every enrolled student of the paper's class in roll
        order, with whatever marks exist merged in."""
        paper = await self._get_paper(paper_id)
        subject = await self.subjects.get(paper.subject_id)
        school_class = await self.classes.get(paper.class_id)
        assert subject is not None and school_class is not None  # FK-guaranteed

        roster = await self.marks.class_roster(paper.class_id)
        by_student = {m.student_id: m for m in await self.marks.list_for_paper(paper_id)}

        rows = []
        for student in roster:
            mark = by_student.get(student.id)
            rows.append(
                StudentMarkRow(
                    student_id=student.id,
                    full_name=student.full_name,
                    admission_number=student.admission_number,
                    marks_obtained=mark.marks_obtained if mark else None,
                    is_absent=mark.is_absent if mark else False,
                    remarks=mark.remarks if mark else None,
                    entered=mark is not None,
                )
            )
        # A student who was marked and later left the class still owns that
        # mark: append them after the roster rather than dropping the row, or
        # the sheet would silently show fewer marks than the count says.
        seated = {student.id for student in roster}
        for student_id, mark in by_student.items():
            if student_id not in seated:
                rows.append(
                    StudentMarkRow(
                        student_id=student_id,
                        full_name="(no longer in this class)",
                        admission_number="—",
                        marks_obtained=mark.marks_obtained,
                        is_absent=mark.is_absent,
                        remarks=mark.remarks,
                        entered=True,
                    )
                )

        return PaperMarksRead(
            paper=self._to_paper_read(paper, subject, school_class, len(by_student)),
            rows=rows,
        )

    async def upsert_marks(
        self, paper_id: UUID, payload: MarksUpsert, *, actor_id: UUID
    ) -> MarksUpsertResult:
        paper = await self._get_paper(paper_id)

        # Only students seated in the paper's class may be marked on it. Checked
        # against the live roster in ONE set operation: a stray id here is
        # either a typo or an attempt to write into another class's sheet.
        seated = {s.id for s in await self.marks.class_roster(paper.class_id)}
        already_marked = {m.student_id for m in await self.marks.list_for_paper(paper_id)}
        allowed = seated | already_marked  # corrections for departed students stay legal
        strays = [str(e.student_id) for e in payload.entries if e.student_id not in allowed]
        if strays:
            raise ValidationError(
                f"{len(strays)} student(s) are not in this paper's class: {', '.join(strays[:5])}"
            )

        over_max = [
            e for e in payload.entries
            if e.marks_obtained is not None and e.marks_obtained > paper.max_marks
        ]
        if over_max:
            raise ValidationError(
                f"Marks above the paper's maximum ({paper.max_marks}) for "
                f"{len(over_max)} student(s)."
            )

        # One sheet may name a student once. Two rows for one student in a
        # single submit is a client bug, and last-write-wins would hide it.
        ids = [e.student_id for e in payload.entries]
        if len(ids) != len(set(ids)):
            raise ValidationError("A student appears more than once in this sheet.")

        saved = await self.marks.upsert_many(
            paper_id=paper.id,
            organization_id=paper.organization_id,
            school_id=paper.school_id,
            entries=[e.model_dump() for e in payload.entries],
        )
        await self._audit(
            AuditAction.EXAM_MARKS_ENTERED,
            entity_type="exam_paper",
            entity_id=paper_id,
            actor_id=actor_id,
            after={"entries": saved},
        )
        logger.info("exam_marks_entered", paper_id=str(paper_id), entries=saved)
        return MarksUpsertResult(saved=saved)

    # -- results -------------------------------------------------------------

    async def class_results(self, exam_id: UUID, class_id: UUID) -> ExamClassResults:
        """The class result sheet: papers as columns, students as rows, ranked.

        Percentage is over the papers actually MARKED for each student (absent
        counts as 0 of that paper's max; unmarked papers do not count at all) --
        see `ExamResultRow.percentage` for why unmarked must not mean zero.
        """
        await self.get_exam(exam_id)
        school_class = await self.classes.get(class_id)
        if school_class is None:
            raise NotFoundError("Class not found.")

        triples = await self.papers.list_for_exam(exam_id, class_id=class_id)
        entered = await self.papers.marks_entered_counts(exam_id)
        papers = [
            self._to_paper_read(paper, subject, klass, entered.get(paper.id, 0))
            for paper, subject, klass in triples
        ]

        marks_by_student: dict[UUID, dict[UUID, Any]] = {}
        for paper, _subject, _klass in triples:
            for mark in await self.marks.list_for_paper(paper.id):
                marks_by_student.setdefault(mark.student_id, {})[paper.id] = mark

        max_by_paper = {p.id: p.max_marks for p in papers}
        roster = await self.marks.class_roster(class_id)

        unranked = []
        for student in roster:
            student_marks = marks_by_student.get(student.id, {})
            cells, obtained, max_counted = [], Decimal(0), 0
            for paper in papers:
                mark = student_marks.get(paper.id)
                cells.append(
                    ResultCell(
                        paper_id=paper.id,
                        marks_obtained=mark.marks_obtained if mark else None,
                        is_absent=mark.is_absent if mark else False,
                    )
                )
                if mark is not None:
                    max_counted += max_by_paper[paper.id]
                    if mark.marks_obtained is not None:
                        obtained += mark.marks_obtained
            percentage = (
                (obtained * 100 / max_counted).quantize(Decimal("0.01"))
                if max_counted
                else Decimal(0)
            )
            unranked.append((student, cells, obtained, max_counted, percentage))

        # Standard competition ranking on percentage: ties share a rank and the
        # rank after a tie skips (91, 91, 88 -> 1, 1, 3).
        unranked.sort(key=lambda row: row[4], reverse=True)
        rows: list[ExamResultRow] = []
        for index, (student, cells, obtained, max_counted, percentage) in enumerate(unranked):
            rank = rows[-1].rank if rows and rows[-1].percentage == percentage else index + 1
            rows.append(
                ExamResultRow(
                    student_id=student.id,
                    full_name=student.full_name,
                    admission_number=student.admission_number,
                    cells=cells,
                    total_obtained=obtained,
                    total_max=max_counted,
                    percentage=percentage,
                    rank=rank,
                )
            )

        return ExamClassResults(
            exam_id=exam_id,
            class_id=class_id,
            class_name=school_class.name,
            papers=papers,
            rows=rows,
        )

    # -- internals -----------------------------------------------------------

    async def _get_paper(self, paper_id: UUID) -> ExamPaper:
        paper = await self.papers.get(paper_id)
        if paper is None:
            raise NotFoundError("Exam paper not found.")
        return paper

    @staticmethod
    def _to_exam_read(exam: Exam, *, paper_count: int = 0) -> ExamRead:
        return ExamRead(
            id=exam.id,
            name=exam.name,
            term_id=exam.term_id,
            start_date=exam.start_date,
            end_date=exam.end_date,
            status=exam.status,
            paper_count=paper_count,
            created_at=exam.created_at,
            updated_at=exam.updated_at,
        )

    @staticmethod
    def _to_paper_read(
        paper: ExamPaper, subject: Subject, school_class: SchoolClass, marks_entered: int
    ) -> ExamPaperRead:
        return ExamPaperRead(
            id=paper.id,
            exam_id=paper.exam_id,
            class_id=paper.class_id,
            class_name=school_class.name,
            subject_id=subject.id,
            subject_code=subject.code,
            subject_name=subject.name,
            scheduled_on=paper.scheduled_on,
            max_marks=paper.max_marks,
            pass_marks=paper.pass_marks,
            marks_entered=marks_entered,
            created_at=paper.created_at,
            updated_at=paper.updated_at,
        )

    async def _audit(
        self,
        action: str,
        *,
        entity_type: str,
        entity_id: UUID,
        actor_id: UUID,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await record_audit(
            self.session,
            organization_id=require_organization_id(),
            school_id=require_school_id(),
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
        )
