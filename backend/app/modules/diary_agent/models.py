"""Diary agent models -- each campus's diary format, and the drafts teachers confirm.

WHY THIS FILE EXISTS
    Schools here send the day's diary home on the class WhatsApp group. Teachers
    already write it on paper, so instead of retyping it they photograph the page
    and send it to the school's WhatsApp number. The agent reads the photo, works
    out the class, writes it in THIS campus's format, shows it back to the teacher,
    and posts it to the class group once they reply OK.

RESPONSIBILITY
    Two tables:
      * `diary_agent_settings`  one row per campus: is the agent on, the message
                                template it writes the diary into, and standing
                                instructions for the model (language, subject
                                names, what to leave out);
      * `diary_drafts`          one row per photo: what the model read, which
                                class/group it is for, the text shown to the
                                teacher, and how the conversation ended.

WHY A DRAFT ROW AND NOT JUST THE OUTBOX
    Between the photo and the post there is a conversation -- "which class?",
    "Maths is page 45 not 44", "OK" -- that spans several webhooks, minutes apart.
    The draft is that conversation's state. Once posted, the outbox row
    (`message_id`) is the record of what parents received.

WHY THE PHOTO IS NOT KEPT
    It is a page of a child's notebook-style diary on a teacher's phone; keeping it
    adds storage and privacy surface for no reader. What the model read from it
    (`content`) and the text posted are kept, which is what anyone asks about later.

INTERACTIONS
    * `TenantMixin` -> RLS; `RequiredSchoolMixin` -> campus scope.
    * `group_id` -> `whatsapp_groups.id`, `message_id` -> `whatsapp_messages.id`,
      both SET NULL so unlinking a group never erases a teacher's history.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, UniqueConstraint
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

DEFAULT_DIARY_TEMPLATE = (
    "*{school}*\n📘 *Daily Diary - {class}*\n🗓️ {day}, {date}\n\n{entries}\n\n{notes}"
)
"""Placeholders: see `service.DIARY_PLACEHOLDERS`. WhatsApp renders *bold*."""

DEFAULT_ENTRY_TEMPLATE = "▪️ *{subject}:* {homework}"
"""One line per subject, joined into `{entries}`."""


class DiaryDraftStatus(StrEnum):
    READING = "reading"
    """The photo is with the model. Also the duplicate guard while it is."""
    NEEDS_CLASS = "needs_class"
    """Read, but the class could not be told from the page; the teacher was asked."""
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    """Formatted and shown to the teacher; waiting for OK, a correction or CANCEL."""
    POSTED = "posted"
    """Queued to the class group (`message_id`). The outbox says whether it went."""
    CANCELLED = "cancelled"
    """The teacher said cancel, sent a newer photo, or let it lapse."""
    FAILED = "failed"
    """Not a diary, unreadable, or the model could not be reached -- see `error`."""


OPEN_STATUSES = (
    DiaryDraftStatus.READING,
    DiaryDraftStatus.NEEDS_CLASS,
    DiaryDraftStatus.AWAITING_CONFIRMATION,
)


class DiaryAgentSettings(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin
):
    """How one campus wants its diary written. Absent row = the defaults, enabled."""

    __tablename__ = "diary_agent_settings"

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """ON by default, unlike the fee notice: nothing posts without a teacher sending
    a photo AND confirming the result, so there is no surprise to guard against."""

    template: Mapped[str] = mapped_column(Text, nullable=False, default=DEFAULT_DIARY_TEMPLATE)
    entry_template: Mapped[str] = mapped_column(
        String(500), nullable=False, default=DEFAULT_ENTRY_TEMPLATE
    )
    instructions: Mapped[str | None] = mapped_column(Text)
    """Standing guidance for the model, in the office's words: "write homework in
    Urdu as it appears", "call Maths 'Mathematics'", "skip the teacher's signature".
    It shapes how the page is READ; the template decides how it is LAID OUT."""

    __table_args__ = (UniqueConstraint("school_id", name="uq_diary_agent_settings_school_id"),)


class DiaryDraft(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One photographed diary page, from arrival to posted (or not)."""

    __tablename__ = "diary_drafts"

    teacher_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reply_chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    """Where the agent answers the teacher (`923001234567@c.us`)."""
    inbound_message_id: Mapped[str] = mapped_column(String(160), nullable=False)
    """WhatsApp's id for the photo message. Unique per campus: a webhook delivered
    twice reads the page once."""

    status: Mapped[DiaryDraftStatus] = mapped_column(
        str_enum(DiaryDraftStatus, name="status"),
        nullable=False,
        default=DiaryDraftStatus.READING,
    )
    diary_date: Mapped[date | None] = mapped_column(Date)
    """The date written on the page, else the day it was sent."""
    class_hint: Mapped[str | None] = mapped_column(String(120))
    """The class as written on the page ("V-B", "Grade 5 Blue"), for the record."""
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """What the model read: `{"entries": [{"subject", "homework"}], "notes"}`."""

    group_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("whatsapp_groups.id", ondelete="SET NULL")
    )
    class_label: Mapped[str | None] = mapped_column(String(120))
    """"Grade 5-B" -- the class the group serves, as written into the message."""
    body: Mapped[str | None] = mapped_column(Text)
    """The formatted diary, exactly as shown to the teacher and then posted."""

    message_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("whatsapp_messages.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "inbound_message_id",
            name="uq_diary_drafts_school_id_inbound_message_id",
        ),
        # The hot read: "this teacher's open draft" on every message they send.
        Index("ix_diary_drafts_school_id_teacher_status", "school_id", "teacher_user_id", "status"),
        Index("ix_diary_drafts_school_id_created_at", "school_id", "created_at"),
    )
