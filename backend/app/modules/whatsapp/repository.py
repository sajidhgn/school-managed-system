"""WhatsApp data access. SQL only -- no business rules.

Organization isolation comes from PostgreSQL RLS. Hand-built joins apply the campus
filter explicitly, for the reason `attendance/repository.py` gives: a joined
`select(...)` never passes through `_base_select`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.models import SchoolClass, Section
from app.modules.auth.models import User
from app.modules.fees.models import FeeStructure, FeeVoucher, VoucherStatus
from app.modules.students.models import Student
from app.modules.whatsapp.models import (
    WhatsAppGroup,
    WhatsAppMessage,
    WhatsAppMessageKind,
    WhatsAppMessageStatus,
    WhatsAppSettings,
)

# A challan a parent can act on. DRAFT is not a bill yet, VOID never was one.
_BILLED = (
    VoucherStatus.ISSUED,
    VoucherStatus.PARTLY_PAID,
    VoucherStatus.PAID,
    VoucherStatus.OVERDUE,
)


@dataclass(frozen=True, slots=True)
class ClassBilling:
    """What one class (or section) was billed for one period, summarised for a notice."""

    challans: int
    due_date: date
    amount: Decimal
    """The MOST COMMON challan subtotal -- the class's standard fee. Not the average:
    one family's concession or carried arrears must not move the figure the whole
    group reads."""
    currency: str


class WhatsAppGroupRepository(BaseRepository[WhatsAppGroup]):
    model = WhatsAppGroup
    sortable_fields = frozenset({"name", "created_at"})

    async def all_with_class(
        self,
    ) -> Sequence[tuple[WhatsAppGroup, SchoolClass, Section | None]]:
        """Every group on the campus with its class and section, in class order."""
        stmt = (
            select(WhatsAppGroup, SchoolClass, Section)
            .join(SchoolClass, SchoolClass.id == WhatsAppGroup.class_id)
            .outerjoin(Section, Section.id == WhatsAppGroup.section_id)
            .order_by(SchoolClass.level, Section.name.nulls_first(), WhatsAppGroup.name)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(WhatsAppGroup.school_id == school_id)
        return [(g, c, s) for g, c, s in (await self.session.execute(stmt)).all()]


class WhatsAppSettingsRepository(BaseRepository[WhatsAppSettings]):
    model = WhatsAppSettings

    async def for_campus(self) -> WhatsAppSettings | None:
        return (await self.session.execute(self._base_select())).scalars().first()


class WhatsAppMessageRepository(BaseRepository[WhatsAppMessage]):
    model = WhatsAppMessage
    sortable_fields = frozenset({"created_at", "sent_at"})

    async def groups_with_fee_notice(self, period_label: str) -> set[UUID]:
        """Groups that already have this period's fee notice, queued or otherwise."""
        stmt = select(WhatsAppMessage.group_id).where(
            WhatsAppMessage.kind == WhatsAppMessageKind.FEE_NOTICE,
            WhatsAppMessage.period_label == period_label,
            WhatsAppMessage.group_id.is_not(None),
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(WhatsAppMessage.school_id == school_id)
        return {gid for gid in (await self.session.execute(stmt)).scalars() if gid is not None}

    async def last_sent(self, group_ids: Iterable[UUID]) -> dict[UUID, datetime]:
        ids = set(group_ids)
        if not ids:
            return {}
        stmt = (
            select(WhatsAppMessage.group_id, func.max(WhatsAppMessage.sent_at))
            .where(
                WhatsAppMessage.group_id.in_(ids),
                WhatsAppMessage.status == WhatsAppMessageStatus.SENT,
            )
            .group_by(WhatsAppMessage.group_id)
        )
        return {gid: at for gid, at in (await self.session.execute(stmt)).all() if at is not None}

    async def queued_ids(self, limit: int) -> list[UUID]:
        """The dispatcher's read: what is waiting, oldest first. Org-wide on purpose --
        the dispatcher drains every campus of the organization its session is bound to."""
        stmt = (
            select(WhatsAppMessage.id)
            .where(WhatsAppMessage.status == WhatsAppMessageStatus.QUEUED)
            .order_by(WhatsAppMessage.created_at, WhatsAppMessage.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def claim(self, message_id: UUID) -> WhatsAppMessage | None:
        """Lock one queued message for sending, or None if another dispatcher has it.

        SKIP LOCKED, so two dispatchers started by mistake share the queue instead of
        both posting the same notice.
        """
        stmt = (
            select(WhatsAppMessage)
            .where(
                WhatsAppMessage.id == message_id,
                WhatsAppMessage.status == WhatsAppMessageStatus.QUEUED,
            )
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def delete_queued_for_group(self, group_id: UUID) -> None:
        stmt = select(WhatsAppMessage).where(
            WhatsAppMessage.group_id == group_id,
            WhatsAppMessage.status == WhatsAppMessageStatus.QUEUED,
        )
        for message in (await self.session.execute(stmt)).scalars():
            await self.session.delete(message)


class WhatsAppLookupRepository:
    """The academics, fee and user reads this module is assembled from."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def school_class(self, class_id: UUID) -> SchoolClass | None:
        stmt = select(SchoolClass).where(
            SchoolClass.id == class_id, SchoolClass.deleted_at.is_(None)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(SchoolClass.school_id == school_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def section(self, section_id: UUID) -> Section | None:
        stmt = select(Section).where(Section.id == section_id, Section.deleted_at.is_(None))
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Section.school_id == school_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def class_billing(
        self, class_id: UUID, section_id: UUID | None, period_label: str
    ) -> ClassBilling | None:
        """Summarise one class's billed challans for one period; None if there are none.

        The class comes through the challan's STRUCTURE (`fee_structures.class_id`),
        which is the class the student was billed as -- not where they sit today, so
        a mid-month transfer does not move last month's challan between groups.
        """
        stmt = (
            select(FeeVoucher.due_date, FeeVoucher.subtotal, FeeVoucher.currency)
            .join(FeeStructure, FeeStructure.id == FeeVoucher.structure_id)
            .where(
                FeeStructure.class_id == class_id,
                FeeVoucher.period_label == period_label,
                FeeVoucher.status.in_(_BILLED),
            )
        )
        if section_id is not None:
            stmt = stmt.join(Student, Student.id == FeeVoucher.student_id).where(
                Student.section_id == section_id
            )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(FeeVoucher.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        if not rows:
            return None
        amount, _ = Counter(row.subtotal for row in rows).most_common(1)[0]
        due, _ = Counter(row.due_date for row in rows).most_common(1)[0]
        return ClassBilling(
            challans=len(rows), due_date=due, amount=amount, currency=rows[0].currency
        )

    async def user_names(self, user_ids: Iterable[UUID | None]) -> dict[UUID, str]:
        ids = {i for i in user_ids if i is not None}
        if not ids:
            return {}
        rows = await self.session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
        return {row[0]: row[1] for row in rows}
