"""WhatsApp API contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.common.schemas import BaseSchema
from app.modules.whatsapp.models import WhatsAppMessageKind, WhatsAppMessageStatus

# WhatsApp's own cap is 65,536 characters; a class notice is a few lines. The tighter
# bound refuses a pasted document before the transport spends minutes typing it.
MAX_MESSAGE_LENGTH = 4000


class WhatsAppGroupWrite(BaseSchema):
    class_id: UUID
    section_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    invite_link: str = Field(min_length=6, max_length=200)
    """The group's invite link (`https://chat.whatsapp.com/AbC123...`) or its bare code."""
    is_active: bool = True
    send_fee_notice: bool = True


class WhatsAppGroupRead(BaseSchema):
    id: UUID
    class_id: UUID
    class_name: str
    section_id: UUID | None
    section_name: str | None
    name: str
    invite_code: str
    chat_id: str | None
    """The resolved WhatsApp group id; null until the campus's number is connected
    (WAHA) and has found the group. Irrelevant to the other transports."""
    is_active: bool
    send_fee_notice: bool
    last_sent_at: datetime | None
    """When anything last went out to this group -- the office's "is it working?"."""


class WhatsAppSettingsWrite(BaseSchema):
    fee_notice_enabled: bool
    send_day: int = Field(ge=1, le=28)
    fee_template: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    monthly_note: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)
    absence_alerts_enabled: bool | None = None
    """Omitted (or null) leaves it as it is, so a client that only edits the fee
    notice cannot switch absence alerts off by not knowing about them."""


class WhatsAppSettingsRead(WhatsAppSettingsWrite):
    absence_alerts_enabled: bool = False
    placeholders: list[str]
    """What `fee_template` may use, so the form can list them without hardcoding."""
    next_send_on: str | None
    """ISO date the next automatic notice is due to be queued; null when off."""


class FeeNoticeQueueRequest(BaseSchema):
    """Queue this month's fee notice now, instead of waiting for the send day."""

    period_label: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    """Defaults to the current month."""
    group_ids: list[UUID] | None = None
    """Only these groups; null = every active group that takes the fee notice."""


class FeeNoticePreview(BaseSchema):
    group_id: UUID
    group_name: str
    body: str | None
    """Null when the group has nothing to announce -- see `reason`."""
    reason: str | None


class CustomMessageRequest(BaseSchema):
    body: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    group_ids: list[UUID] | None = None
    """Null = every active group on the campus."""


class QueueResult(BaseSchema):
    queued: int
    skipped: list[FeeNoticePreview] = Field(default_factory=list)
    """Groups nothing was queued for, each with why."""


class WhatsAppMessageRead(BaseSchema):
    id: UUID
    group_id: UUID | None
    group_name: str
    kind: WhatsAppMessageKind
    period_label: str | None
    body: str
    status: WhatsAppMessageStatus
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime
    created_by_name: str | None


class WhatsAppConnectionRead(BaseSchema):
    """The campus's linked WhatsApp number, as the WAHA gateway sees it."""

    backend: str
    """`WHATSAPP_BACKEND`. Only `waha` has a connection to manage."""
    configured: bool
    """False when the backend is not WAHA -- the screen then explains the setup."""
    status: str | None
    """WAHA's session status: STOPPED, STARTING, SCAN_QR_CODE, WORKING or FAILED.
    Null when the campus has never connected."""
    phone: str | None
    push_name: str | None
    unresolved_groups: int
    """Active groups whose WhatsApp id is not known yet. Non-zero while WORKING
    means the linked number is not a member of those groups."""


class WhatsAppQrRead(BaseSchema):
    mimetype: str
    data: str
    """Base64 image: render as `data:{mimetype};base64,{data}` and scan it with the
    school's phone (WhatsApp -> Linked devices -> Link a device)."""
