"""Diary agent API contracts."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from app.common.schemas import BaseSchema
from app.modules.diary_agent.models import DiaryDraftStatus
from app.modules.whatsapp.schemas import MAX_MESSAGE_LENGTH


class DiaryAgentSettingsWrite(BaseSchema):
    enabled: bool
    template: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    """The whole message. `{entries}` is where the subject lines go."""
    entry_template: str = Field(min_length=1, max_length=500)
    """One subject's line, repeated for each subject into `{entries}`."""
    instructions: str | None = Field(default=None, max_length=2000)
    """Standing guidance for the model reading the page, in plain words."""


class DiaryAgentSettingsRead(DiaryAgentSettingsWrite):
    placeholders: list[str]
    """What `template` may use."""
    entry_placeholders: list[str]
    """What `entry_template` may use."""


class DiaryPreviewRead(BaseSchema):
    body: str
    """A sample diary written in the given format -- what parents would read."""


class DiaryDraftRead(BaseSchema):
    id: UUID
    teacher_name: str | None
    status: DiaryDraftStatus
    diary_date: date | None
    class_hint: str | None
    class_label: str | None
    group_id: UUID | None
    body: str | None
    message_id: UUID | None
    error: str | None
    created_at: datetime
    updated_at: datetime
