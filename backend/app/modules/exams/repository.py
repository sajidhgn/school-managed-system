"""Exam data access. SQL only -- no business rules.

Organization isolation comes from PostgreSQL RLS; campus isolation from the
shared repository injecting the active school. The aggregate queries below apply
the same scope explicitly, mirroring `academics/repository.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.models import SchoolClass, Section, Subject
from app.modules.exams.models import Exam, ExamMark, ExamPaper
from app.modules.students.models import Student, StudentStatus


class ExamRepository(BaseRepository[Exam]):
    model = Exam
    sortable_fields = frozenset({"name", "start_date", "status", "created_at"})

    async def get_by_name(self, name: str) -> Exam | None:
        return await self.find_one(Exam.name == name)

    def search_filter(self, term: str):  # type: ignore[no-untyped-def]
        return Exam.name.ilike(f"%{term}%")

    async def paper_counts(self) -> dict[UUID, int]:
        """Papers per exam for the whole (RLS-scoped) school, in ONE grouped
        query -- the exams list prints a count per row, and counting per exam
        would be an N+1 that grows with the school's history."""
        stmt = (
            select(ExamPaper.exam_id, func.count(ExamPaper.id))
            .where(ExamPaper.deleted_at.is_(None))
            .group_by(ExamPaper.exam_id)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(ExamPaper.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return {exam_id: int(count) for exam_id, count in rows}


class ExamPaperRepository(BaseRepository[ExamPaper]):
    model = ExamPaper
    sortable_fields = frozenset({"scheduled_on", "created_at"})

    async def get_paper(self, exam_id: UUID, class_id: UUID, subject_id: UUID) -> ExamPaper | None:
        return await self.find_one(
            ExamPaper.exam_id == exam_id,
            ExamPaper.class_id == class_id,
            ExamPaper.subject_id == subject_id,
        )

    async def list_for_exam(
        self, exam_id: UUID, *, class_id: UUID | None = None
    ) -> Sequence[tuple[ExamPaper, Subject, SchoolClass]]:
        """Papers joined to their subject and class in ONE query, ordered by
        class level then subject code -- the order a result sheet prints in.

        Returns triples rather than lazy relationships for the same reason
        `ClassSubjectRepository.list_for_class` does: per-row loads are the N+1
        this method exists to prevent.
        """
        stmt = (
            self._base_select()
            .join(Subject, Subject.id == ExamPaper.subject_id)
            .join(SchoolClass, SchoolClass.id == ExamPaper.class_id)
            .where(ExamPaper.exam_id == exam_id)
            .order_by(SchoolClass.level, Subject.code)
            .add_columns(Subject, SchoolClass)
        )
        if class_id is not None:
            stmt = stmt.where(ExamPaper.class_id == class_id)
        rows = (await self.session.execute(stmt)).all()
        return [(paper, subject, school_class) for paper, subject, school_class in rows]

    async def marks_entered_counts(self, exam_id: UUID) -> dict[UUID, int]:
        """Marks entered per paper of one exam, ONE grouped query."""
        stmt = (
            select(ExamMark.paper_id, func.count(ExamMark.id))
            .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
            .where(ExamPaper.exam_id == exam_id, ExamMark.deleted_at.is_(None))
            .group_by(ExamMark.paper_id)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(ExamMark.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return {paper_id: int(count) for paper_id, count in rows}

    async def marks_exist(self, exam_id: UUID) -> bool:
        """Whether ANY paper of this exam has marks -- read before deleting the
        exam, so the refusal can say why instead of surfacing a cascade."""
        stmt = (
            select(func.count())
            .select_from(ExamMark)
            .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
            .where(ExamPaper.exam_id == exam_id, ExamMark.deleted_at.is_(None))
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0) > 0


class ExamMarkRepository(BaseRepository[ExamMark]):
    model = ExamMark
    sortable_fields = frozenset({"created_at"})

    async def list_for_paper(self, paper_id: UUID) -> Sequence[ExamMark]:
        stmt = self._base_select().where(ExamMark.paper_id == paper_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def count_for_paper(self, paper_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ExamMark)
            .where(ExamMark.paper_id == paper_id, ExamMark.deleted_at.is_(None))
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def class_roster(self, class_id: UUID) -> Sequence[Student]:
        """Every enrolled student seated in any section of `class_id`, ordered by
        admission number -- the roll order a mark sheet is keyed in.

        Read here rather than through the students module because the marks
        screen needs exactly this shape (id, name, admission number) joined to
        the paper's class, and the enrollment service's roster is per-section.
        """
        stmt = (
            select(Student)
            .join(Section, Section.id == Student.section_id)
            .where(
                Section.class_id == class_id,
                Student.status == StudentStatus.ACTIVE,
                Student.deleted_at.is_(None),
            )
            .order_by(Student.admission_number)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Student.school_id == school_id)
        return (await self.session.execute(stmt)).scalars().all()

    # -- the students directory's result filter ------------------------------
    #
    # Subquery builders, not executed lists: `students/service.py` embeds them
    # in `Student.id IN (...)` conditions, the same shape as the fee filter's
    # `students_owing`. What counts as passed/failed/absent is defined HERE,
    # beside the mark model, so the directory never re-derives marking rules.

    def students_marked(self, exam_id: UUID):  # type: ignore[no-untyped-def]
        """Students with ANY mark row (including absences) in this exam."""
        return (
            select(ExamMark.student_id)
            .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
            .where(ExamPaper.exam_id == exam_id, ExamMark.deleted_at.is_(None))
        )

    def students_absent(self, exam_id: UUID):  # type: ignore[no-untyped-def]
        """Students who missed at least one paper of this exam."""
        return (
            select(ExamMark.student_id)
            .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
            .where(
                ExamPaper.exam_id == exam_id,
                ExamMark.deleted_at.is_(None),
                ExamMark.is_absent.is_(True),
            )
        )

    def students_below_pass(self, exam_id: UUID):  # type: ignore[no-untyped-def]
        """Students marked below the pass line on at least one paper.

        Only papers that DECLARE a pass line count -- a school that never set
        `pass_marks` has no fail list, rather than an invented 40% one.
        """
        return (
            select(ExamMark.student_id)
            .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
            .where(
                ExamPaper.exam_id == exam_id,
                ExamMark.deleted_at.is_(None),
                ExamMark.is_absent.is_(False),
                ExamPaper.pass_marks.is_not(None),
                ExamMark.marks_obtained < ExamPaper.pass_marks,
            )
        )

    async def summary_by_student(
        self, exam_id: UUID, student_ids: set[UUID]
    ) -> dict[UUID, tuple]:
        """Per-student exam totals for one PAGE of the directory, in ONE grouped
        query: (obtained, max over marked papers, failed papers, absent papers).
        Per-row queries here would be an N+1 that grows with the page size."""
        if not student_ids:
            return {}
        stmt = (
            select(
                ExamMark.student_id,
                func.coalesce(
                    func.sum(ExamMark.marks_obtained).filter(ExamMark.is_absent.is_(False)), 0
                ),
                func.sum(ExamPaper.max_marks),
                func.count()
                .filter(
                    ExamMark.is_absent.is_(False),
                    ExamPaper.pass_marks.is_not(None),
                    ExamMark.marks_obtained < ExamPaper.pass_marks,
                )
                .label("failed"),
                func.count().filter(ExamMark.is_absent.is_(True)).label("absent"),
            )
            .select_from(ExamMark)
            .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
            .where(
                ExamPaper.exam_id == exam_id,
                ExamMark.student_id.in_(student_ids),
                ExamMark.deleted_at.is_(None),
            )
            .group_by(ExamMark.student_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}

    async def upsert_many(
        self,
        *,
        paper_id: UUID,
        organization_id: UUID,
        school_id: UUID,
        entries: Sequence[dict],
    ) -> int:
        """Write a paper's mark sheet in ONE statement.

        `INSERT ... ON CONFLICT (paper_id, student_id) DO UPDATE`, not
        read-then-write per row: the mark sheet is re-submitted whole after every
        correction, and five hundred SELECT-or-INSERT round trips per save is how
        a marks screen becomes unusable on school wifi. The conflict target is
        the table's uniqueness guard, so a concurrent double-submit degrades to
        last-write-wins instead of a 409 mid-sheet.
        """
        if not entries:
            return 0
        stmt = pg_insert(ExamMark).values(
            [
                {
                    "paper_id": paper_id,
                    "organization_id": organization_id,
                    "school_id": school_id,
                    **entry,
                }
                for entry in entries
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["paper_id", "student_id"],
            set_={
                "marks_obtained": stmt.excluded.marks_obtained,
                "is_absent": stmt.excluded.is_absent,
                "remarks": stmt.excluded.remarks,
                "updated_at": func.now(),
                # A re-entered mark un-deletes: the sheet is the source of truth.
                "deleted_at": None,
            },
        )
        await self.session.execute(stmt)
        return len(entries)
