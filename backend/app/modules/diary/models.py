"""Diary models -- the daily homework page a section takes home.

WHY THIS FILE EXISTS
    Schools in this market send a "diary" home every day: one sheet per class,
    a row per subject, the assignment written beside it ("Pg 85 full L+w"). Today
    it is typed into a phone image editor and forwarded on WhatsApp. This is the
    record behind that sheet, so the class teacher writes it once, subject teachers
    fill their own rows, and the sheet is rendered from data instead of retyped.

RESPONSIBILITY
    One table, `diary_entries`: this section, this date, this subject, this text.

INTERACTIONS
    * `TenantMixin` (organization_id) -> RLS; `RequiredSchoolMixin` (school_id) ->
      campus scope. Both inherited from the section on write.
    * `section_id` -> `sections.id`; `subject_id` -> `subjects.id`.
    * WHICH subjects a page has is not stored here: it is the section's class
      curriculum (`class_subjects`). An entry only exists once someone writes one,
      so an empty page costs no rows.

WHY THERE IS NO "DIARY PAGE" ROW
    Attendance needs a register row because "not taken" must be distinguishable
    from "everyone present". A diary has no such ambiguity -- a subject with no
    entry simply has no homework -- so a parent row would be a second place for
    the date and section to live, and nothing would read it.

WHY NO SOFT DELETE
    Clearing a subject's homework deletes its row. The diary is a day-to-day
    instruction to children, not a record anything downstream is computed from,
    and every write is still in `audit_logs` with the text before and after.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import (
    RequiredSchoolMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class DiaryEntry(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One subject's homework for one section on one day."""

    __tablename__ = "diary_entries"

    section_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    """`Date`, not `DateTime`, for the reason `AttendanceSession.session_date`
    gives: the diary belongs to a school DAY, and a timezone would move it."""

    content: Mapped[str] = mapped_column(Text, nullable=False)
    """Free text, any script. Urdu, Arabic and English share one page routinely,
    so direction is decided where it is rendered, never stored."""

    written_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL: a teacher leaving must not erase the homework they set.
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    """Whoever last changed the text -- the subject teacher or the class teacher."""

    __table_args__ = (
        UniqueConstraint(
            "section_id",
            "entry_date",
            "subject_id",
            name="uq_diary_entries_section_id_entry_date_subject_id",
        ),
        # The two hot reads: one section's page for a date (the unique index above
        # serves it), and the whole campus for a date.
        Index("ix_diary_entries_school_id_entry_date", "school_id", "entry_date"),
    )
