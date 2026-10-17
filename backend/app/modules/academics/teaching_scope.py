"""What a member sees when they may not look across the whole campus.

=============================================================================
WHO IS BOUND: EVERYONE WITHOUT `class:view_all`
=============================================================================
    A caller holding `class:view_all` sees every class, section and student. Anyone
    else is bound to their ASSIGNMENTS. It is a permission, not a role check, so the
    principal decides per role in the role editor: the seeded teacher role is bound,
    the principal and accountant are not, and a "Head of Year" custom role is
    whichever the principal ticks.

=============================================================================
WHAT "ASSIGNED" MEANS
=============================================================================
    Two links, both holding a user id:
      * class teacher of a SECTION -> that section, and every subject of its class
        (the class teacher answers for the whole timetable of their section);
      * subject teacher on a CLASS's curriculum -> that subject, in every section of
        the class, because the curriculum is keyed by class, not section.

    So a class teacher of 9-A sees 9-A's students and all of Grade 9's subjects; a
    maths teacher for Grade 9 sees 9-A and 9-B's students and only maths.

    Returned as SQL subqueries rather than id lists, so each caller drops one more
    condition into the WHERE it already builds -- no extra round trip, and RLS
    bounds the subquery to the tenant exactly as it does the outer query.

    Every helper takes `teacher_id: UUID` -- the value `assigned_teacher` returns
    when the caller is bound. Callers pass None through as "no condition".
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, literal, or_, select, tuple_, union
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811

from app.modules.academics.models import ClassSubject, Section

VIEW_ALL_CLASSES = "class:view_all"


def assigned_teacher(user_id: UUID, permissions: frozenset[str]) -> UUID | None:
    """The user whose assignments bound this caller's view, or None for no bound."""
    return None if VIEW_ALL_CLASSES in permissions else user_id


def _subject_class_ids(teacher_id: UUID) -> Select[tuple[UUID]]:
    return select(ClassSubject.class_id).where(
        ClassSubject.teacher_id == teacher_id,
        ClassSubject.deleted_at.is_(None),
    )


def _class_teacher_class_ids(teacher_id: UUID) -> Select[tuple[UUID]]:
    return select(Section.class_id).where(
        Section.class_teacher_id == teacher_id,
        Section.deleted_at.is_(None),
    )


def taught_section_ids(teacher_id: UUID) -> Select[tuple[UUID]]:
    """Sections the teacher runs as class teacher or teaches a subject in."""
    return select(Section.id).where(
        Section.deleted_at.is_(None),
        or_(
            Section.class_teacher_id == teacher_id,
            Section.class_id.in_(_subject_class_ids(teacher_id)),
        ),
    )


def taught_class_ids(teacher_id: UUID) -> Select[tuple[UUID]]:
    """Classes the teacher has at least one assignment in.

    A subject link counts even before the class has sections, so a newly
    timetabled teacher sees the class rather than nothing.
    """
    both = union(_class_teacher_class_ids(teacher_id), _subject_class_ids(teacher_id))
    return select(both.subquery().c[0])


def teaches_subject(teacher_id: UUID, class_id: Any, subject_id: Any) -> ColumnElement[bool]:
    """Whether the (class, subject) pair is one the teacher answers for.

    True for every subject of a class they are class teacher in, and for the exact
    pairs they are subject teacher of. `class_id` / `subject_id` are columns of the
    caller's own query (or plain ids) -- an exam paper, a book, a curriculum
    link.
    """
    # Plain ids are bound as UUID literals so `IN` and the tuple compare type-check
    # in PostgreSQL the same way a column would.
    if isinstance(class_id, UUID):
        class_id = literal(class_id, PgUUID(as_uuid=True))
    if isinstance(subject_id, UUID):
        subject_id = literal(subject_id, PgUUID(as_uuid=True))
    pairs = select(ClassSubject.class_id, ClassSubject.subject_id).where(
        ClassSubject.teacher_id == teacher_id,
        ClassSubject.deleted_at.is_(None),
    )
    return or_(
        class_id.in_(_class_teacher_class_ids(teacher_id)),
        tuple_(class_id, subject_id).in_(pairs),
    )
