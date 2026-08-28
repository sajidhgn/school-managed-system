"""Guardian API contracts -- staff registry, portal auth, and portal reads.

WHY SEPARATE FROM models.py
    These describe what a client may SEND and what it WILL RECEIVE. `organization_id`
    and `school_id` appear in no Create schema: both come from the verified token,
    never from a request body. Accepting either would be a mass-assignment hole that
    writes into another tenant.

WHY THE AUTH SCHEMAS LIVE HERE AND NOT IN `auth/schemas.py`
    They are a different surface with a different principal. Sharing `LoginResponse`
    between staff and guardians would mean one shape carrying a membership for one
    caller and a child list for the other, and every consumer branching on which.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import EmailStr, Field

from app.common.schemas import BaseSchema
from app.modules.guardians.models import GuardianRelationship

# ---------------------------------------------------------------------------
# Staff-facing registry
# ---------------------------------------------------------------------------


class GuardianCreate(BaseSchema):
    """Register a guardian, or attach to the identity that already holds this phone.

    `phone` is the identity key. The service normalises it to E.164 and REUSES an
    existing identity when one matches -- which is what makes a father with children
    at two campuses one login rather than two. That reuse is invisible here on
    purpose: the front office types a number, and whether it was already known is not
    a decision a clerk should have to make.
    """

    phone: str = Field(min_length=7, max_length=32, examples=["+923001234567"])
    full_name: str = Field(min_length=1, max_length=200, examples=["Muhammad Aslam"])
    email: EmailStr | None = None
    cnic: str | None = Field(default=None, max_length=32)
    occupation: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    alternate_phone: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=1000)
    preferred_locale: str | None = Field(default=None, max_length=10, examples=["ur"])


class GuardianUpdate(BaseSchema):
    """PATCH semantics: omitted fields are left untouched.

    `phone` is absent DELIBERATELY. Changing it changes which handset can sign in as
    this person, which is a credential change, not a profile edit -- it goes through
    `PUT /guardians/{id}/phone`, which is separately permissioned and audited.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    cnic: str | None = Field(default=None, max_length=32)
    occupation: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    alternate_phone: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=1000)
    preferred_locale: str | None = Field(default=None, max_length=10)


class GuardianPhoneChange(BaseSchema):
    """Re-point a guardian record at a different handset."""

    phone: str = Field(min_length=7, max_length=32)


class GuardianPortalToggle(BaseSchema):
    enabled: bool


class LinkedStudentRead(BaseSchema):
    """One child as seen from the guardian's record."""

    link_id: UUID
    student_id: UUID
    school_id: UUID
    admission_number: str
    full_name: str
    section_id: UUID | None
    status: str
    relationship_type: GuardianRelationship
    relationship_label: str | None
    is_primary_contact: bool
    is_emergency_contact: bool
    can_pickup: bool
    receives_notifications: bool
    can_view_results: bool


class GuardianRead(BaseSchema):
    id: UUID
    identity_id: UUID
    phone: str
    full_name: str
    email: str | None
    cnic: str | None
    occupation: str | None
    address: str | None
    alternate_phone: str | None
    portal_enabled: bool
    notes: str | None
    preferred_locale: str
    identity_status: str
    last_login_at: datetime | None
    student_count: int
    created_at: datetime
    updated_at: datetime


class GuardianDetail(GuardianRead):
    """A guardian with every child they are linked to, for the detail screen."""

    students: list[LinkedStudentRead]


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


class GuardianLinkCreate(BaseSchema):
    """Attach a guardian to a child.

    Every flag defaults to the SAFE value rather than the convenient one:
    `can_pickup` is false because handing a child to an unauthorised adult is the
    worst outcome this table can produce, and `is_primary_contact` is false because
    exactly one guardian may hold it and silently stealing it from the mother when
    the father is added later is not a decision a default should make.
    """

    student_id: UUID
    relationship_type: GuardianRelationship = GuardianRelationship.OTHER
    relationship_label: str | None = Field(default=None, max_length=60)
    is_primary_contact: bool = False
    is_emergency_contact: bool = False
    can_pickup: bool = False
    receives_notifications: bool = True
    can_view_results: bool = True


class GuardianLinkUpdate(BaseSchema):
    relationship_type: GuardianRelationship | None = None
    relationship_label: str | None = Field(default=None, max_length=60)
    is_primary_contact: bool | None = None
    is_emergency_contact: bool | None = None
    can_pickup: bool | None = None
    receives_notifications: bool | None = None
    can_view_results: bool | None = None


class StudentGuardianRead(BaseSchema):
    """One guardian as seen from the student's record -- the contact card."""

    link_id: UUID
    guardian_id: UUID
    identity_id: UUID
    full_name: str
    phone: str
    alternate_phone: str | None
    email: str | None
    cnic: str | None
    relationship_type: GuardianRelationship
    relationship_label: str | None
    is_primary_contact: bool
    is_emergency_contact: bool
    can_pickup: bool
    receives_notifications: bool
    can_view_results: bool
    portal_enabled: bool


# ---------------------------------------------------------------------------
# Portal authentication
# ---------------------------------------------------------------------------


class OtpRequest(BaseSchema):
    phone: str = Field(min_length=7, max_length=32, examples=["+923001234567"])


class OtpRequestResponse(BaseSchema):
    """Deliberately identical whether or not the number is known.

    ENUMERATION IS THE WHOLE POINT OF THIS SHAPE. An honest "no guardian with that
    number" turns an unauthenticated endpoint into a way to test whether a given
    person has a child at a given school -- which is exactly the information a
    stalker or a rival school would want, and which no parent consented to publish.

    So the response is the same in both branches, down to the masked number echoed
    back (derived from the caller's own input, not from a row). `retry_after_seconds`
    is the only variable, and it is a function of the caller's own request rate.
    """

    message: str
    phone_masked: str
    expires_in_seconds: int
    retry_after_seconds: int


class OtpVerifyRequest(BaseSchema):
    phone: str = Field(min_length=7, max_length=32)
    code: str = Field(min_length=4, max_length=10, examples=["482913"])


class GuardianContextSummary(BaseSchema):
    """One organization this guardian holds records in -- the context picker."""

    guardian_id: UUID
    organization_id: UUID
    organization_name: str
    student_count: int
    schools: list[str]


class GuardianTokenPair(BaseSchema):
    """Returned ONLY to a caller that opted in with `X-Token-Transport: body`.

    Browsers get httpOnly cookies and nothing else. This exists for the test suite
    and for a future native parent app, which has no cookie jar. It is not a hole a
    malicious page can exploit: a cross-origin page cannot set that header without
    CORS approval, and the response is not readable to it if it could.
    """

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int


class GuardianLoginResponse(BaseSchema):
    """The result of verifying a code.

    THREE OUTCOMES, ONE SHAPE:
      * `authenticated`  -- exactly one usable organization; a full session is issued.
      * `select_required` -- several; `contexts` is populated and the caller must POST
        to `/guardian/auth/context`. Mirrors the staff multi-membership flow.
      * `no_access`      -- the handset is known but no organization currently exposes
        records to it (portal disabled, or every child unlinked). Distinguished from
        a wrong code so the parent is told to call the school rather than made to
        retype a code that will never work.
    """

    status: str
    guardian: GuardianProfile | None = None
    contexts: list[GuardianContextSummary] = Field(default_factory=list)
    tokens: GuardianTokenPair | None = None


class GuardianContextRequest(BaseSchema):
    guardian_id: UUID


class GuardianProfile(BaseSchema):
    """Who the portal thinks you are."""

    identity_id: UUID
    guardian_id: UUID
    organization_id: UUID
    organization_name: str
    full_name: str
    phone: str
    email: str | None
    preferred_locale: str


class GuardianChildRead(BaseSchema):
    """One child, as the parent portal shows them.

    A NARROWER PROJECTION than `StudentRead`, and that is the security control. The
    staff record carries the other guardian's phone number, the family address and
    free-text notes; a separated parent must not read the other's contact details out
    of the portal. Fields are added here one at a time, deliberately.
    """

    student_id: UUID
    school_id: UUID
    school_name: str
    admission_number: str
    full_name: str
    date_of_birth: date | None
    section_id: UUID | None
    status: str
    relationship_type: GuardianRelationship
    can_view_results: bool


class GuardianMessageResponse(BaseSchema):
    message: str


GuardianLoginResponse.model_rebuild()
