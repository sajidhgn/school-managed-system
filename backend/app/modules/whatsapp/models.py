"""WhatsApp models -- class groups, the campus's monthly-notice settings, the outbox.

WHY THIS FILE EXISTS
    Every class in this market has a parents' WhatsApp group, and on the 1st the
    office posts the same message to each one: "October challans are out, due by the
    10th, Rs 4,500". This module posts it for them from the challans the fee schedule
    already generated, and lets the office post any other notice to chosen groups.

RESPONSIBILITY
    Three tables:
      * `whatsapp_groups`    which WhatsApp group belongs to which class (or section);
      * `whatsapp_settings`  one row per campus: is the monthly notice on, on which
                             day, and the template and standing note it is built from;
      * `whatsapp_messages`  the OUTBOX -- every post, queued, then sent or failed.

WHY AN OUTBOX AND NOT A SEND
    The configured transport (`common/whatsapp/sender.py`) may be pywhatkit, which
    drives a browser on a desktop and cannot run inside the API. So nothing here
    sends: the API and the nightly job only QUEUE, and `app.cli send-whatsapp` drains
    the queue wherever the transport can actually run. The outbox is also the history
    the office reads to answer "did the fee message go out to 5-B?".

INTERACTIONS
    * `TenantMixin` -> RLS; `RequiredSchoolMixin` -> campus scope.
    * `class_id` -> `classes.id`, `section_id` -> `sections.id`.
    * The fee notice reads `fee_vouchers` (via `structure_id` -> `fee_structures`)
      and never writes them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.db.mixins import (
    RequiredSchoolMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

DEFAULT_FEE_TEMPLATE = (
    "Dear Parents of {class},\n"
    "Fee challans for {month} have been issued.\n"
    "Monthly fee: {amount}\n"
    "Last date to pay: {due_date}\n"
    "Please pay before the due date to avoid a late fee.\n"
    "- {school}"
)
"""The placeholders `render_fee_notice` fills; documented on the settings screen."""


class WhatsAppMessageKind(StrEnum):
    FEE_NOTICE = "fee_notice"
    """The monthly challan notice, at most one per group per period."""
    CUSTOM = "custom"
    """Anything the office typed and chose groups for."""


class WhatsAppMessageStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    """Handed to the transport without an error. For pywhatkit that means typed into
    WhatsApp Web -- it is not a delivery receipt, and nothing here claims one."""
    FAILED = "failed"


class WhatsAppGroup(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One parents' group, tied to the class (and optionally the section) it serves."""

    __tablename__ = "whatsapp_groups"

    class_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        index=True,
    )
    """Null for one group serving the whole class; set when each section has its
    own. The fee notice then counts only that section's challans."""

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    """What the office calls it ("Grade 5-A Parents") -- shown in lists, never sent."""

    invite_code: Mapped[str] = mapped_column(String(64), nullable=False)
    """The code from the group's invite link (`chat.whatsapp.com/<code>`). WhatsApp
    Web opens a group by it, so it is the group's address for the transport. Stored
    as the bare code; the service accepts the full link and strips it."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Off = receives nothing, automatic or custom, but keeps its link and history."""

    send_fee_notice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Lets one group (e.g. a staff group linked to a class) opt out of the monthly
    fee message while still receiving custom notices."""

    __table_args__ = (
        UniqueConstraint(
            "school_id", "invite_code", name="uq_whatsapp_groups_school_id_invite_code"
        ),
    )


class WhatsAppSettings(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """The campus's monthly fee notice: on or off, which day, and what it says."""

    __tablename__ = "whatsapp_settings"

    fee_notice_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """OFF until the office turns it on -- posting to every parents' group is not
    something a school should discover it agreed to by linking a group."""

    send_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Day of the month the notice is queued, 1-28 for the reason
    `FeeBillingSchedule.generate_day` gives. If that month's challans are not issued
    yet on the day (drafts awaiting approval), each later nightly pass tries again
    until they are or until they fall due."""

    fee_template: Mapped[str] = mapped_column(Text, nullable=False, default=DEFAULT_FEE_TEMPLATE)

    monthly_note: Mapped[str | None] = mapped_column(Text)
    """The office's standing "custom message" appended under the fee notice every
    month -- holidays, uniform reminders, PTM date. Blank = nothing appended."""

    __table_args__ = (
        UniqueConstraint("school_id", name="uq_whatsapp_settings_school_id"),
        CheckConstraint("send_day BETWEEN 1 AND 28", name="send_day_in_month"),
    )


class WhatsAppMessage(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One post to one group: queued, then sent or failed. The outbox AND the history."""

    __tablename__ = "whatsapp_messages"

    group_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL: removing a group must not erase the record of what was posted to it.
        ForeignKey("whatsapp_groups.id", ondelete="SET NULL"),
        index=True,
    )
    group_name: Mapped[str] = mapped_column(String(120), nullable=False)
    """Snapshot, so the history still reads correctly after a group is renamed or removed."""
    invite_code: Mapped[str] = mapped_column(String(64), nullable=False)
    """Snapshot of where it is going. A queued message keeps its destination even if
    the group's link is changed before the dispatcher runs."""

    kind: Mapped[WhatsAppMessageKind] = mapped_column(
        str_enum(WhatsAppMessageKind, name="kind"), nullable=False
    )
    period_label: Mapped[str | None] = mapped_column(String(40))
    """"2026-10" for a fee notice; null for a custom message."""

    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WhatsAppMessageStatus] = mapped_column(
        str_enum(WhatsAppMessageStatus, name="status"),
        nullable=False,
        default=WhatsAppMessageStatus.QUEUED,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    """Null when the nightly job queued it -- the schedule did, not a person."""

    __table_args__ = (
        # The dispatcher's read: what is waiting, oldest first.
        Index("ix_whatsapp_messages_status_created_at", "status", "created_at"),
        Index("ix_whatsapp_messages_school_id_created_at", "school_id", "created_at"),
        # ONE FEE NOTICE PER GROUP PER MONTH, held by the database rather than by a
        # bookmark: a nightly pass that retries, overlaps, or runs after a crash
        # cannot post October's reminder to 5-A twice. Partial, created by hand in
        # the migration:
        #   UNIQUE (group_id, period_label) WHERE kind = 'fee_notice'
    )
