"""Tenancy request/response contracts: organizations and schools."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, Field, StringConstraints

from app.common.schemas import BaseSchema

THEME_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
"""Exactly `#RRGGBB`. No shorthand, no alpha, no named colours: the value is
interpolated into print stylesheets and PDF templates, and one canonical form
means those consumers never need their own parser."""

ThemeColor = Annotated[str, StringConstraints(pattern=THEME_COLOR_PATTERN)]

ThemeColors = Annotated[list[ThemeColor], Field(min_length=1, max_length=5)]
"""An ORDERED palette: first is primary, second secondary; consumers read by
index. Capped at five because a sixth "brand colour" is a symptom, not a brand.
An empty list is not a valid palette -- "no colours of our own" is expressed as
null (inherit / unbranded), never as `[]`, so there is exactly one spelling."""

LOGO_URL_PATTERN = r"^(https?://|data:image/)"
"""The two shapes a logo can take: a link, or the image itself.

Uploads arrive as `data:image/...` URIs -- the browser downscales the file and
inlines it, because this deployment has no object store and the frontend hides
the API origin from the browser, so a served-file URL has nowhere to live. The
prefix check means the value is always safe to interpolate into an `<img src>`
(no `javascript:` and no scheme-relative surprises); it is NOT an image format
validation, which the browser performs on render anyway."""

LogoUrl = Annotated[str, StringConstraints(pattern=LOGO_URL_PATTERN, max_length=300_000)]
"""300k chars ~= a 220 KB image base64-encoded -- generous for a client-side
downscaled logo (typically under 50 KB) while still refusing a full-resolution
photograph that would bloat every OrganizationRead response carrying it."""

# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------


class OrganizationRead(BaseSchema):
    id: UUID
    name: str
    slug: str
    owner_user_id: UUID
    country: str | None
    timezone: str
    currency: str
    locale: str
    status: str
    billing_email: str | None
    tax_id: str | None
    logo_url: str | None
    theme_colors: list[str] | None
    created_at: datetime


class OrganizationUpdate(BaseSchema):
    """PATCH body. Every field optional -- omitted means "leave unchanged".

    `slug` is absent on purpose: it appears in URLs and in links already sent by
    email, so changing it silently breaks bookmarks. It is set once at signup.
    """

    name: str | None = Field(default=None, min_length=2, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    locale: str | None = Field(default=None, max_length=10)
    billing_email: EmailStr | None = None
    tax_id: str | None = Field(default=None, max_length=64)
    logo_url: LogoUrl | None = None
    theme_colors: ThemeColors | None = None


class TransferOwnershipRequest(BaseSchema):
    """Hand the organization to another member.

    Identified by membership, not by user id or email: the new owner must ALREADY be
    a member of this organization. Accepting an arbitrary email would let an owner
    transfer to someone outside the org, who would then hold billing rights over data
    they were never granted access to.
    """

    new_owner_membership_id: UUID


class CardDesignConfig(BaseSchema):
    """A campus's student ID card template -- the principal's design decisions.

    Every field has a default equal to how the card rendered before this feature
    existed, so a NULL `card_design` and an empty `{}` both mean "the standard
    card" and old saved designs stay valid as knobs are added. Closed enums, not
    free CSS: the frontend renders these into ONE audited card layout, and a
    principal cannot (and should not) express a design that hides the child's
    name or pushes the QR off the card edge.
    """

    design: Literal[
        # The quiet originals.
        "classic", "bold", "gradient", "stripe", "minimal",
        # The print-shop styles: colour panels, sweeps and geometric bands
        # modelled on physical sample cards, with icon-chip detail lines.
        "chevron", "panel", "wave", "mosaic",
        # The modern set: split and outlined headers, decorative backgrounds
        # (dots, grid, ribbon, blob, rings, corner triangles), trailing sweep.
        "duotone", "outline", "ribbon", "dots", "blob",
        "rings", "tide", "slate", "banner", "corner", "grid",
        # Combinations: panels, patterns and fills recomposed.
        "prism", "crest", "frame", "sash", "orbit",
        "aurora", "pillar", "halo", "graphite", "breeze",
        # The laminated lanyard card: solid bands top and bottom.
        "band",
    ] = "classic"
    """A closed catalogue. Each value maps to token choices in ONE audited
    frontend layout — never free CSS — so every design keeps the child's
    name, the contact line and the QR where they belong."""
    orientation: Literal["landscape", "portrait"] = "landscape"

    logo_position: Literal["start", "center", "end"] = "center"
    """Where the school logo sits in the header band."""

    photo_shape: Literal["rounded", "circle", "square"] = "rounded"
    """The photo frame's corner treatment -- `circle` also squares the frame."""
    photo_size: Literal["sm", "md", "lg"] = "md"
    photo_position: Literal["start", "end"] = "start"
    """Which side of the details the photo sits on (landscape only; portrait
    always centres it)."""

    # Which optional lines print. The name is NOT optional -- an ID card that
    # does not identify is not an ID card, so there is no switch for it.
    show_admission_number: bool = True
    show_class: bool = True
    show_date_of_birth: bool = True
    show_guardian_name: bool = True

    contact_number: Literal["guardian", "emergency", "school"] = "guardian"
    """Whose phone the "if found, please call" line shows. `emergency` falls
    back to the guardian's number at render time when a child has no separate
    emergency contact -- a blank line on a lost card helps nobody."""

    show_qr: bool = True
    """A QR encoding the student's name, roll number and class, so any phone
    camera identifies the card's owner without an app or a database."""

    rules: list[Annotated[str, StringConstraints(max_length=120)]] = Field(
        default_factory=list, max_length=6
    )
    """Printed as a numbered list on the card's BACK -- the school's conduct
    lines ("Be on time...", "Wear the proper uniform...") from the laminated
    sample cards. Empty means the back simply omits the list. Capped at six
    lines of 120 characters: the back is 86mm tall and shares it with the
    office address, the QR and the signature."""

    show_validity: bool = True
    """The back's "Issued ... / Expires ..." line. Expiry is rendered as one
    year after the student's enrolment date -- a session card, reissued yearly
    like the sample's 2025-26."""

    found_notice: str = Field(default="", max_length=300)
    """The back's "if found" paragraph, verbatim. Empty (the default) renders
    the standard line composed at print time from the school's name and the
    chosen contact number -- so it never goes stale when either changes. A
    school that wants different wording (another language, a legal line)
    types it here and owns keeping it current."""

    contact_line: str = Field(default="", max_length=120)
    """The FRONT footer, verbatim. Empty renders the standard "If found,
    please call {number}" using `contact_number`'s pick. Same trade as
    `found_notice`: custom text is exact but the school keeps it current."""


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------


class SchoolRead(BaseSchema):
    id: UUID
    organization_id: UUID
    name: str
    code: str
    slug: str
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    logo_url: str | None
    theme_colors: list[str] | None
    card_design: CardDesignConfig | None
    academic_year_start_month: int
    timezone: str
    locale: str
    status: str
    created_at: datetime


class SchoolCreate(BaseSchema):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=1, max_length=32)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    academic_year_start_month: int = Field(default=4, ge=1, le=12)
    timezone: str = Field(default="UTC", max_length=64)
    locale: str = Field(default="en", max_length=10)


class SchoolUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    logo_url: LogoUrl | None = None
    """Explicit null reverts this campus to the organization's logo (PATCH
    semantics above); same for `theme_colors`."""
    theme_colors: ThemeColors | None = None
    card_design: CardDesignConfig | None = None
    """Explicit null restores the standard card."""
    academic_year_start_month: int | None = Field(default=None, ge=1, le=12)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=10)
