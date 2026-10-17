"""Diary agent business rules for the office -- the campus's format, and the history.

The conversation with teachers lives in `conversation.py`; this is the part staff
reach through the web app: configure how the diary is written, preview it, and see
what teachers have sent.

THE FORMAT IS A TEMPLATE, NOT A PROMPT
    Every campus lays its diary out differently -- a header with the school's name,
    an emoji per subject, the date first or last. That layout is a template with
    placeholders, filled in code, so what the office sees in the preview is
    exactly what parents receive. The model only READS the page; how the result
    looks is never left to it. `instructions` is the one free-text lever on the
    model, for things a template cannot say ("keep Urdu homework in Urdu").
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams
from app.core.context import require_organization_id, require_school_id
from app.modules.diary_agent.models import (
    DEFAULT_DIARY_TEMPLATE,
    DEFAULT_ENTRY_TEMPLATE,
    DiaryAgentSettings,
)
from app.modules.diary_agent.repository import DiaryAgentSettingsRepository, DiaryDraftRepository
from app.modules.diary_agent.schemas import (
    DiaryAgentSettingsRead,
    DiaryAgentSettingsWrite,
    DiaryDraftRead,
    DiaryPreviewRead,
)
from app.modules.tenancy.models import School
from app.modules.whatsapp.repository import WhatsAppLookupRepository
from app.modules.whatsapp.service import render

DIARY_PLACEHOLDERS = ("school", "class", "date", "day", "entries", "notes", "teacher")
ENTRY_PLACEHOLDERS = ("subject", "homework")

_BLANK_RUN_RE = re.compile(r"\n{3,}")

_SAMPLE_ENTRIES = (
    ("English", "Write the new words of Lesson 6 three times. Learn the poem."),
    ("Maths", "Exercise 4.2, Q1 to Q5 in the copy."),
    ("Urdu", "سبق نمبر 5 کے سوالات یاد کریں۔"),  # noqa: RUF001 -- a real Urdu full stop
    ("Science", "Draw and label the parts of a plant, page 34."),
)


def render_diary(
    template: str,
    entry_template: str,
    *,
    school: str,
    class_label: str,
    diary_date: date,
    entries: Sequence[tuple[str, str]],
    notes: str | None,
    teacher: str,
) -> str:
    """Write a diary into a campus's format.

    An empty `{notes}` would leave a hole in the message, so runs of blank lines
    are collapsed and the ends trimmed -- a template can always carry the notes
    line without every diary that has none looking broken.
    """
    lines = "\n".join(
        render(entry_template, {"subject": subject, "homework": homework}).rstrip()
        for subject, homework in entries
    )
    body = render(
        template,
        {
            "school": school,
            "class": class_label,
            "date": diary_date.strftime("%d %b %Y"),
            "day": diary_date.strftime("%A"),
            "entries": lines,
            "notes": (notes or "").strip(),
            "teacher": teacher,
        },
    )
    body = "\n".join(line.rstrip() for line in body.splitlines())
    return _BLANK_RUN_RE.sub("\n\n", body).strip()


class DiaryAgentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = DiaryAgentSettingsRepository(session)
        self.drafts = DiaryDraftRepository(session)

    async def get_settings(self) -> DiaryAgentSettingsRead:
        return self._settings_read(await self.settings.for_campus())

    async def put_settings(
        self, payload: DiaryAgentSettingsWrite, *, actor_id: UUID
    ) -> DiaryAgentSettingsRead:
        row = await self.settings.for_campus()
        values: dict[str, Any] = payload.model_dump()
        values["instructions"] = (payload.instructions or "").strip() or None
        if row is None:
            row = await self.settings.create(
                **values,
                organization_id=require_organization_id(),
                school_id=require_school_id(),
            )
        else:
            row = await self.settings.update(row, **values)
        await record_audit(
            self.session,
            organization_id=require_organization_id(),
            school_id=require_school_id(),
            actor_user_id=actor_id,
            action=AuditAction.DIARY_AGENT_SETTINGS_SET,
            entity_type="diary_agent_settings",
            entity_id=row.id,
            after={"enabled": row.enabled},
        )
        return self._settings_read(row)

    async def preview(self, payload: DiaryAgentSettingsWrite) -> DiaryPreviewRead:
        """A made-up diary in the proposed format, before it is saved."""
        school = await self.session.get(School, require_school_id())
        return DiaryPreviewRead(
            body=render_diary(
                payload.template,
                payload.entry_template,
                school=school.name if school else "",
                class_label="Grade 5-B",
                diary_date=date.today(),
                entries=_SAMPLE_ENTRIES,
                notes="Tomorrow is the science quiz. Bring your art copy.",
                teacher="Ms. Ayesha",
            )
        )

    async def list_drafts(self, params: PageParams) -> Page[DiaryDraftRead]:
        rows, total = await self.drafts.list(params=params)
        names = await WhatsAppLookupRepository(self.session).user_names(
            d.teacher_user_id for d in rows
        )
        return Page.create(
            [
                DiaryDraftRead(
                    id=d.id,
                    teacher_name=names.get(d.teacher_user_id) if d.teacher_user_id else None,
                    status=d.status,
                    diary_date=d.diary_date,
                    class_hint=d.class_hint,
                    class_label=d.class_label,
                    group_id=d.group_id,
                    body=d.body,
                    message_id=d.message_id,
                    error=d.error,
                    created_at=d.created_at,
                    updated_at=d.updated_at,
                )
                for d in rows
            ],
            total,
            params,
        )

    @staticmethod
    def _settings_read(row: DiaryAgentSettings | None) -> DiaryAgentSettingsRead:
        return DiaryAgentSettingsRead(
            enabled=row.enabled if row else True,
            template=row.template if row else DEFAULT_DIARY_TEMPLATE,
            entry_template=row.entry_template if row else DEFAULT_ENTRY_TEMPLATE,
            instructions=row.instructions if row else None,
            placeholders=list(DIARY_PLACEHOLDERS),
            entry_placeholders=list(ENTRY_PLACEHOLDERS),
        )
