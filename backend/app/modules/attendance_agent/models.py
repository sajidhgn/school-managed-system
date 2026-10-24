"""Attendance agent models -- a register a teacher sent on WhatsApp, until they say OK.

WHY THIS FILE EXISTS
    A teacher can take attendance by messaging the school's WhatsApp number:

        teacher  Nursery-A absent 12, 13, 15
        agent    Attendance - Nursery-A ... Absent (3): 12 Ali, 13 Sara, 15 Bilal.
                 Everyone else present (27 of 30). Reply OK to submit.
        teacher  ok
        agent    ✅ Attendance submitted for Nursery-A: 27 present, 3 absent.

    Between the message and the OK there is a conversation -- "which class?",
    "13 was present actually", "OK" -- spanning several webhooks, minutes apart.
    `attendance_chat_drafts` is that conversation's state: one row per register a
    teacher sends, holding what they asked for until they confirm it.

WHY THE REGISTER IS NOT TOUCHED UNTIL THE OK
    The obvious design opens the register as soon as the message arrives and lets
    the OK submit it. It would also mean an unanswered message leaves a half-made
    register on the principal's board, and CANCEL has to undo a write. Here the
    whole request waits in this row, and the OK opens, marks and submits the
    register in ONE transaction -- the same three calls the web register makes, so
    the register's own rules (teaching scope, roster, submitted-is-final) still
    decide. Nothing in `attendance_*` knows WhatsApp exists.

WHAT IS KEPT
    The teacher's own words (`request_text`), what they were read as, and the
    register it became. When a parent disputes an absence, "the teacher sent
    'absent 12, 13, 15' at 08:12 and confirmed the names" is the answer.

INTERACTIONS
    * `TenantMixin` -> RLS; `RequiredSchoolMixin` -> campus scope.
    * `section_id` -> `sections.id`, `attendance_session_id` ->
      `attendance_sessions.id`, `teacher_user_id` -> `users.id`, all SET NULL: a
      chat transcript must never stop a section, register or user from going.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.db.mixins import (
    RequiredSchoolMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AttendanceChatStatus(StrEnum):
    NEEDS_CLASS = "needs_class"
    """Understood, but which class it is for could not be told; the teacher was asked."""
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    """Matched to names and shown to the teacher; waiting for OK, a change or CANCEL."""
    SUBMITTED = "submitted"
    """The register was opened, marked and submitted (`attendance_session_id`)."""
    CANCELLED = "cancelled"
    """The teacher said cancel, sent a newer register, or let it lapse."""
    FAILED = "failed"
    """Could not be submitted -- already submitted, roster changed -- see `error`."""


OPEN_STATUSES = (AttendanceChatStatus.NEEDS_CLASS, AttendanceChatStatus.AWAITING_CONFIRMATION)


class AttendanceChatDraft(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin
):
    """One register sent on WhatsApp, from the message to submitted (or not)."""

    __tablename__ = "attendance_chat_drafts"

    teacher_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reply_chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    """Where the agent answers the teacher (`923001234567@c.us`)."""
    inbound_message_id: Mapped[str] = mapped_column(String(160), nullable=False)
    """WhatsApp's id for the message that started it. Unique per campus: a webhook
    delivered twice is read once."""

    status: Mapped[AttendanceChatStatus] = mapped_column(
        str_enum(AttendanceChatStatus, name="status"),
        nullable=False,
        default=AttendanceChatStatus.AWAITING_CONFIRMATION,
    )
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    """What the teacher typed, corrections appended one per line."""
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    """The day the register is for: the day the message arrived."""
    class_hint: Mapped[str | None] = mapped_column(String(120))
    """The class as the teacher wrote it ("nur a"), for the record."""

    marks: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """What the message was read as, by ROLL NUMBER:
    `{"marks": [{"roll_number": "12", "status": "absent"}], "all_present": false}`.
    Roll numbers, not students, because the class may not be known yet."""
    resolved: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """Those roll numbers matched against the class, exactly as previewed:
    `{"students": {"<student id>": "absent"}, "unknown": ["45"], "roster": 30}`.
    The OK applies THIS, so the teacher confirms the names they were shown."""

    section_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sections.id", ondelete="SET NULL")
    )
    class_label: Mapped[str | None] = mapped_column(String(120))
    """"Nursery-A" -- the section, as written into the preview."""
    attendance_session_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("attendance_sessions.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "inbound_message_id",
            name="uq_attendance_chat_drafts_school_id_inbound_message_id",
        ),
        # The hot read: "this teacher's open register" on every message they send.
        Index(
            "ix_attendance_chat_drafts_school_id_teacher_status",
            "school_id",
            "teacher_user_id",
            "status",
        ),
    )
