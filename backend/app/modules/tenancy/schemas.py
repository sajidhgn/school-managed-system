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


class ChallanPaymentAccount(BaseSchema):
    """One "pay us here" line printed across the head of every fee challan.

    A list rather than two fixed fields because a campus collects through whatever
    it has arranged -- a bank account, an Easypaisa wallet, a second branch for the
    afternoon shift -- and the count changes between schools and between terms. The
    holder's name is separate from the number because that is the pair a bank
    counter checks: a transfer to the right number under the wrong title bounces,
    and a parent reading one string cannot tell which half was mistyped.
    """

    label: str = Field(min_length=1, max_length=60, examples=["Easypaisa", "Meezan Bank"])
    number: str = Field(min_length=1, max_length=40, examples=["0324-6797307"])
    """Kept as TEXT, verbatim, never as digits. An IBAN has letters, a wallet number
    has a leading zero, and both are copied character for character at a counter."""

    holder: str = Field(default="", max_length=80, examples=["M. Imtiaz"])
    """The account title. Empty prints the number alone."""


class ChallanDesignConfig(BaseSchema):
    """A campus's printed fee challan -- the office's layout decisions.

    Same contract as `CardDesignConfig`: every field defaults to how the challan
    rendered before this feature existed, so a NULL `challan_design` and an empty
    `{}` both mean "the standard challan" and saved designs stay valid as knobs are
    added. Closed toggles, not free layout -- the renderer owns ONE audited grid,
    and an office cannot express a challan that loses the amount or the due date.
    """

    copies: list[Literal["bank", "school", "student"]] = Field(
        default=["bank", "school", "student"], min_length=1, max_length=3
    )
    """Which detachable copies print, in the order they are torn off.

    THE DEFAULT IS ALL THREE, and it is a functional default rather than a stylistic
    one: the bank keeps one, stamps and returns one for the school, and the parent
    keeps one as proof. A single-copy challan is refused at the counter. A school
    whose parents pay online and never see a counter trims the list; nobody should
    start there. At least one, because a challan with no copies is a blank page."""

    payment_accounts: list[ChallanPaymentAccount] = Field(default_factory=list, max_length=4)
    """Printed full width under the copy name. Empty prints no account band at all,
    which is right for a campus that only takes cash at its own window. Capped at
    four: a fifth account on a page carrying three copies of itself costs a line the
    fee lines need, and a parent reading five numbers picks the wrong one."""

    show_admission_number: bool = True
    show_roll_number: bool = True
    """The roll number is read from the student's enrollment for the challan's own
    academic year -- the number the register is sorted by that session, not whatever
    they hold now. A student with no enrollment row for the year simply prints
    without it."""

    show_father_name: bool = True
    show_contact: bool = True
    """The primary guardian's name and phone. A campus that hands challans to
    students in class rather than posting them turns both off -- a page carrying a
    family's phone number is a page that must not be left on a desk."""

    show_amount_in_words: bool = True
    """The total spelled out below the fee table. Defends the figure against a pen:
    see `app.common.money`."""

    show_signature_block: bool = True
    """The "Received Amount By Officials" / "Stamp & Signature" footer. Off for a
    school that reconciles entirely from bank statements and wants the paper
    shorter."""

    footer_note: str = Field(default="", max_length=200)
    """Replaces the standard "quote the challan number" line, verbatim. Empty renders
    the standard wording, which stays current on its own; custom text is exact but
    the school owns keeping it so."""


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
    challan_design: ChallanDesignConfig | None
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
    logo_url: LogoUrl | None = None
    """The campus's own logo. Omitted, it inherits the organization's."""
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
    challan_design: ChallanDesignConfig | None = None
    """Explicit null restores the standard challan."""
    academic_year_start_month: int | None = Field(default=None, ge=1, le=12)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=10)
