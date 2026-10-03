"""WhatsApp business rules -- which group hears what, and when.

THE TWO THINGS THIS MODULE POSTS
    * The MONTHLY FEE NOTICE. On the campus's send day, every active group that
      takes it gets one message built from `fee_template` and THAT CLASS'S issued
      challans for the month: the standard fee, the due date, the month. The office's
      standing `monthly_note` is appended under it.
    * CUSTOM MESSAGES the office types and sends to chosen groups, any time.

WHAT THE FEE NOTICE NEVER SAYS
    Any one family's dues. A class group is shared, so the notice states the class's
    standard fee (the most common challan amount) and the due date -- nothing a
    parent could not already read on the school's own fee schedule.

WHY A GROUP CAN BE SKIPPED
    A notice is only queued when the class has ISSUED challans for the period. A
    campus whose schedule generates DRAFTS has nothing to announce until someone
    issues them; the nightly pass keeps checking after the send day and queues the
    notice the night after they are issued -- unless the challans are already past
    due, at which point a "please pay by" message would be wrong rather than late.

INTERACTIONS
    * Reads classes/sections, fee vouchers and structures; never writes them.
    * Writes only `whatsapp_*` tables. Sending is `jobs.dispatch_outbox`'s job.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams
from app.core.context import require_organization_id, require_school_id
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.models import SchoolClass, Section
from app.modules.tenancy.models import School
from app.modules.whatsapp.models import (
    DEFAULT_FEE_TEMPLATE,
    WhatsAppGroup,
    WhatsAppMessage,
    WhatsAppMessageKind,
    WhatsAppMessageStatus,
    WhatsAppSettings,
)
from app.modules.whatsapp.repository import (
    ClassBilling,
    WhatsAppGroupRepository,
    WhatsAppLookupRepository,
    WhatsAppMessageRepository,
    WhatsAppSettingsRepository,
)
from app.modules.whatsapp.schemas import (
    CustomMessageRequest,
    FeeNoticePreview,
    FeeNoticeQueueRequest,
    QueueResult,
    WhatsAppGroupRead,
    WhatsAppGroupWrite,
    WhatsAppMessageRead,
    WhatsAppSettingsRead,
    WhatsAppSettingsWrite,
)

logger = get_logger(__name__)

PLACEHOLDERS = ("class", "month", "amount", "due_date", "school", "challans")

# `https://chat.whatsapp.com/AbCdEf123...`, with or without scheme or a trailing
# query, or the bare code. Real codes are 20-24 characters; the range is lenient.
_INVITE_RE = re.compile(
    r"^(?:(?:https?://)?chat\.whatsapp\.com/(?:invite/)?)?([A-Za-z0-9]{10,40})(?:[/?#].*)?$"
)
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def parse_invite_code(link: str) -> str:
    match = _INVITE_RE.match(link.strip())
    if match is None:
        raise ValidationError(
            "Paste the group's invite link, e.g. https://chat.whatsapp.com/AbC123... "
            "(Group info → Invite via link).",
            code="INVALID_INVITE_LINK",
        )
    return match.group(1)


def render(template: str, values: dict[str, str]) -> str:
    """Fill `{name}` placeholders. Unknown ones are left as typed, and a stray brace
    is just a brace -- `str.format` would raise on both, mid-run, for one school."""
    return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def format_amount(amount: Decimal, currency: str) -> str:
    if currency == "PKR":
        return f"Rs {amount:,.0f}" if amount == amount.to_integral() else f"Rs {amount:,.2f}"
    return f"{currency} {amount:,.2f}"


def current_period(today: date) -> str:
    return f"{today.year:04d}-{today.month:02d}"


def _month_name(period_label: str) -> str:
    year, month = (int(p) for p in period_label.split("-"))
    return date(year, month, 1).strftime("%B %Y")


class WhatsAppService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.groups = WhatsAppGroupRepository(session)
        self.settings = WhatsAppSettingsRepository(session)
        self.messages = WhatsAppMessageRepository(session)
        self.lookup = WhatsAppLookupRepository(session)

    # -- groups -------------------------------------------------------------

    async def list_groups(self) -> list[WhatsAppGroupRead]:
        rows = await self.groups.all_with_class()
        last = await self.messages.last_sent(g.id for g, _, _ in rows)
        return [self._group_read(g, c, s, last.get(g.id)) for g, c, s in rows]

    async def create_group(
        self, payload: WhatsAppGroupWrite, *, actor_id: UUID
    ) -> WhatsAppGroupRead:
        school_class, section = await self._class_and_section(payload.class_id, payload.section_id)
        code = parse_invite_code(payload.invite_link)
        try:
            async with self.session.begin_nested():
                group = await self.groups.create(
                    class_id=school_class.id,
                    section_id=section.id if section else None,
                    name=payload.name,
                    invite_code=code,
                    is_active=payload.is_active,
                    send_fee_notice=payload.send_fee_notice,
                    organization_id=school_class.organization_id,
                    school_id=school_class.school_id,
                )
        except IntegrityError as exc:
            raise self._duplicate_link() from exc
        await self._audit(
            AuditAction.WHATSAPP_GROUP_CREATED,
            "whatsapp_group",
            group.id,
            actor_id,
            after={"name": group.name, "class_id": str(group.class_id)},
        )
        return self._group_read(group, school_class, section, None)

    async def update_group(
        self, group_id: UUID, payload: WhatsAppGroupWrite, *, actor_id: UUID
    ) -> WhatsAppGroupRead:
        group = await self._group_or_404(group_id)
        school_class, section = await self._class_and_section(payload.class_id, payload.section_id)
        before = {
            "name": group.name,
            "invite_code": group.invite_code,
            "is_active": group.is_active,
        }
        code = parse_invite_code(payload.invite_link)
        try:
            async with self.session.begin_nested():
                group = await self.groups.update(
                    group,
                    class_id=school_class.id,
                    section_id=section.id if section else None,
                    name=payload.name,
                    invite_code=code,
                    is_active=payload.is_active,
                    send_fee_notice=payload.send_fee_notice,
                )
        except IntegrityError as exc:
            raise self._duplicate_link() from exc
        await self._audit(
            AuditAction.WHATSAPP_GROUP_UPDATED,
            "whatsapp_group",
            group.id,
            actor_id,
            before=before,
            after={
                "name": group.name,
                "invite_code": group.invite_code,
                "is_active": group.is_active,
            },
        )
        last = await self.messages.last_sent([group.id])
        return self._group_read(group, school_class, section, last.get(group.id))

    async def delete_group(self, group_id: UUID, *, actor_id: UUID) -> None:
        """Removes the link. Messages already SENT stay in the history; ones still
        queued are dropped -- removing a group is how the office stops a post."""
        group = await self._group_or_404(group_id)
        await self.messages.delete_queued_for_group(group.id)
        await self.session.delete(group)
        await self.session.flush()
        await self._audit(
            AuditAction.WHATSAPP_GROUP_DELETED,
            "whatsapp_group",
            group_id,
            actor_id,
            before={"name": group.name, "invite_code": group.invite_code},
        )

    # -- settings -----------------------------------------------------------

    async def get_settings(self, *, today: date | None = None) -> WhatsAppSettingsRead:
        row = await self.settings.for_campus()
        return self._settings_read(row, today or date.today())

    async def put_settings(
        self, payload: WhatsAppSettingsWrite, *, actor_id: UUID
    ) -> WhatsAppSettingsRead:
        row = await self.settings.for_campus()
        values = payload.model_dump()
        values["monthly_note"] = (payload.monthly_note or "").strip() or None
        if row is None:
            row = await self.settings.create(
                **values,
                organization_id=require_organization_id(),
                school_id=require_school_id(),
            )
        else:
            row = await self.settings.update(row, **values)
        await self._audit(
            AuditAction.WHATSAPP_SETTINGS_SET,
            "whatsapp_settings",
            row.id,
            actor_id,
            after={"fee_notice_enabled": row.fee_notice_enabled, "send_day": row.send_day},
        )
        return self._settings_read(row, date.today())

    # -- the fee notice ---------------------------------------------------

    async def preview_fee_notices(self, period_label: str | None = None) -> list[FeeNoticePreview]:
        """What each group WOULD receive for the period, without queuing anything."""
        period = period_label or current_period(date.today())
        settings = await self.settings.for_campus()
        school_name = await self._school_name()
        previews: list[FeeNoticePreview] = []
        for group, school_class, section in await self.groups.all_with_class():
            if not (group.is_active and group.send_fee_notice):
                continue
            billing = await self.lookup.class_billing(group.class_id, group.section_id, period)
            previews.append(
                self._fee_notice(
                    group, school_class, section, billing, settings, period, school_name
                )
            )
        return previews

    async def queue_fee_notices(
        self,
        request: FeeNoticeQueueRequest,
        *,
        actor_id: UUID | None,
        today: date | None = None,
        scheduled: bool = False,
    ) -> QueueResult:
        """Queue the period's fee notice for each eligible group, at most once each.

        `scheduled` is the nightly pass: it additionally declines a notice whose
        challans are already past due. A human pressing "Send now" is trusted to
        know what they are posting.
        """
        today = today or date.today()
        period = request.period_label or current_period(today)
        wanted = set(request.group_ids) if request.group_ids is not None else None
        settings = await self.settings.for_campus()
        school_name = await self._school_name()
        already = await self.messages.groups_with_fee_notice(period)

        queued = 0
        skipped: list[FeeNoticePreview] = []
        for group, school_class, section in await self.groups.all_with_class():
            if wanted is not None and group.id not in wanted:
                continue
            if not (group.is_active and group.send_fee_notice):
                if wanted is not None:
                    skipped.append(
                        self._skip(group, "Group is paused or opted out of fee notices.")
                    )
                continue
            if group.id in already:
                skipped.append(self._skip(group, f"The {period} fee notice was already queued."))
                continue
            billing = await self.lookup.class_billing(group.class_id, group.section_id, period)
            notice = self._fee_notice(
                group, school_class, section, billing, settings, period, school_name
            )
            if notice.body is None:
                skipped.append(notice)
                continue
            if scheduled and billing is not None and billing.due_date < today:
                skipped.append(self._skip(group, "Challans are already past due."))
                continue
            # A savepoint per row: the partial unique index is the real once-only
            # guard, and a concurrent pass hitting it must cost this group, not the
            # whole campus's batch.
            try:
                async with self.session.begin_nested():
                    self.session.add(
                        self._message(
                            group, WhatsAppMessageKind.FEE_NOTICE, notice.body, actor_id, period
                        )
                    )
            except IntegrityError:
                skipped.append(self._skip(group, f"The {period} fee notice was already queued."))
                continue
            queued += 1

        if queued:
            await self._audit(
                AuditAction.WHATSAPP_FEE_NOTICE_QUEUED,
                "whatsapp_settings",
                settings.id if settings else None,
                actor_id,
                after={"period_label": period, "queued": queued, "scheduled": scheduled},
            )
            logger.info("whatsapp_fee_notices_queued", period_label=period, queued=queued)
        return QueueResult(queued=queued, skipped=skipped)

    async def queue_scheduled_fee_notices(self, today: date) -> int:
        """The nightly pass for this campus: on or after the send day, queue what is due."""
        settings = await self.settings.for_campus()
        if settings is None or not settings.fee_notice_enabled or today.day < settings.send_day:
            return 0
        result = await self.queue_fee_notices(
            FeeNoticeQueueRequest(), actor_id=None, today=today, scheduled=True
        )
        return result.queued

    # -- custom messages --------------------------------------------------

    async def queue_custom(self, payload: CustomMessageRequest, *, actor_id: UUID) -> QueueResult:
        body = payload.body.strip()
        wanted = set(payload.group_ids) if payload.group_ids is not None else None
        targets = [
            g
            for g, _, _ in await self.groups.all_with_class()
            if g.is_active and (wanted is None or g.id in wanted)
        ]
        if not targets:
            raise ValidationError("Choose at least one active group.", code="NO_GROUPS")
        for group in targets:
            self.session.add(self._message(group, WhatsAppMessageKind.CUSTOM, body, actor_id, None))
        await self.session.flush()
        await self._audit(
            AuditAction.WHATSAPP_MESSAGE_QUEUED,
            "whatsapp_message",
            None,
            actor_id,
            after={"groups": len(targets), "body": body[:200]},
        )
        return QueueResult(queued=len(targets))

    # -- the outbox -------------------------------------------------------

    async def list_messages(
        self, params: PageParams, status: WhatsAppMessageStatus | None = None
    ) -> Page[WhatsAppMessageRead]:
        conditions = [WhatsAppMessage.status == status] if status else []
        rows, total = await self.messages.list(*conditions, params=params)
        names = await self.lookup.user_names(m.created_by_user_id for m in rows)
        return Page.create(
            [
                WhatsAppMessageRead(
                    id=m.id,
                    group_id=m.group_id,
                    group_name=m.group_name,
                    kind=m.kind,
                    period_label=m.period_label,
                    body=m.body,
                    status=m.status,
                    attempts=m.attempts,
                    last_error=m.last_error,
                    sent_at=m.sent_at,
                    created_at=m.created_at,
                    created_by_name=names.get(m.created_by_user_id)
                    if m.created_by_user_id
                    else None,
                )
                for m in rows
            ],
            total,
            params,
        )

    async def retry_message(self, message_id: UUID) -> None:
        message = await self.messages.get(message_id)
        if message is None:
            raise NotFoundError("Message not found.")
        if message.status is not WhatsAppMessageStatus.FAILED:
            raise ConflictError("Only a failed message can be retried.", code="NOT_FAILED")
        await self.messages.update(message, status=WhatsAppMessageStatus.QUEUED, last_error=None)

    async def cancel_message(self, message_id: UUID) -> None:
        message = await self.messages.get(message_id)
        if message is None:
            raise NotFoundError("Message not found.")
        if message.status is WhatsAppMessageStatus.SENT:
            raise ConflictError("That message has already been sent.", code="ALREADY_SENT")
        await self.session.delete(message)
        await self.session.flush()

    # -- internals --------------------------------------------------------

    def _fee_notice(
        self,
        group: WhatsAppGroup,
        school_class: SchoolClass,
        section: Section | None,
        billing: ClassBilling | None,
        settings: WhatsAppSettings | None,
        period: str,
        school_name: str,
    ) -> FeeNoticePreview:
        if billing is None:
            return self._skip(
                group,
                f"No issued challans for {_month_name(period)} in this class yet "
                "(drafts are not announced).",
            )
        template = settings.fee_template if settings else DEFAULT_FEE_TEMPLATE
        body = render(
            template,
            {
                "class": f"{school_class.name}-{section.name}" if section else school_class.name,
                "month": _month_name(period),
                "amount": format_amount(billing.amount, billing.currency),
                "due_date": billing.due_date.strftime("%d %b %Y"),
                "school": school_name,
                "challans": str(billing.challans),
            },
        ).strip()
        if settings and settings.monthly_note:
            body = f"{body}\n\n{settings.monthly_note}"
        return FeeNoticePreview(group_id=group.id, group_name=group.name, body=body, reason=None)

    @staticmethod
    def _skip(group: WhatsAppGroup, reason: str) -> FeeNoticePreview:
        return FeeNoticePreview(group_id=group.id, group_name=group.name, body=None, reason=reason)

    @staticmethod
    def _message(
        group: WhatsAppGroup,
        kind: WhatsAppMessageKind,
        body: str,
        actor_id: UUID | None,
        period: str | None,
    ) -> WhatsAppMessage:
        return WhatsAppMessage(
            group_id=group.id,
            group_name=group.name,
            invite_code=group.invite_code,
            kind=kind,
            period_label=period,
            body=body,
            status=WhatsAppMessageStatus.QUEUED,
            attempts=0,
            created_by_user_id=actor_id,
            organization_id=group.organization_id,
            school_id=group.school_id,
        )

    def _settings_read(self, row: WhatsAppSettings | None, today: date) -> WhatsAppSettingsRead:
        enabled = row.fee_notice_enabled if row else False
        send_day = row.send_day if row else 1
        next_send: str | None = None
        if enabled:
            if today.day <= send_day:
                next_send = date(today.year, today.month, send_day).isoformat()
            else:
                year, month = (
                    (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                )
                next_send = date(year, month, send_day).isoformat()
        return WhatsAppSettingsRead(
            fee_notice_enabled=enabled,
            send_day=send_day,
            fee_template=row.fee_template if row else DEFAULT_FEE_TEMPLATE,
            monthly_note=row.monthly_note if row else None,
            placeholders=list(PLACEHOLDERS),
            next_send_on=next_send,
        )

    @staticmethod
    def _group_read(
        group: WhatsAppGroup,
        school_class: SchoolClass,
        section: Section | None,
        last_sent_at: datetime | None,
    ) -> WhatsAppGroupRead:
        return WhatsAppGroupRead(
            id=group.id,
            class_id=school_class.id,
            class_name=school_class.name,
            section_id=section.id if section else None,
            section_name=section.name if section else None,
            name=group.name,
            invite_code=group.invite_code,
            is_active=group.is_active,
            send_fee_notice=group.send_fee_notice,
            last_sent_at=last_sent_at,
        )

    async def _class_and_section(
        self, class_id: UUID, section_id: UUID | None
    ) -> tuple[SchoolClass, Section | None]:
        school_class = await self.lookup.school_class(class_id)
        if school_class is None:
            raise NotFoundError("Class not found.")
        if section_id is None:
            return school_class, None
        section = await self.lookup.section(section_id)
        if section is None or section.class_id != school_class.id:
            raise ValidationError(
                f"That section is not part of {school_class.name}.", code="SECTION_NOT_IN_CLASS"
            )
        return school_class, section

    async def _group_or_404(self, group_id: UUID) -> WhatsAppGroup:
        group = await self.groups.get(group_id)
        if group is None:
            raise NotFoundError("WhatsApp group not found.")
        return group

    async def _school_name(self) -> str:
        school = await self.session.get(School, require_school_id())
        return school.name if school else ""

    @staticmethod
    def _duplicate_link() -> ConflictError:
        return ConflictError(
            "Another group on this campus already uses that invite link.",
            code="DUPLICATE_INVITE_LINK",
        )

    async def _audit(
        self,
        action: str,
        entity_type: str,
        entity_id: UUID | None,
        actor_id: UUID | None,
        *,
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
