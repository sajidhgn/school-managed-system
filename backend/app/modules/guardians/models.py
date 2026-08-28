"""Guardian models -- the parent registry and its own identity surface.

WHY THIS FILE EXISTS
    `students.models` deferred a `guardians` table with an explicit note: promote it
    "when parent logins arrive (a guardian signing in to see two children)". That
    moment is now. Everything parent-facing -- absence alerts, fee challans, report
    cards, pickup authorisation -- needs to answer "who is reachable for this child,
    and may they sign in?", and four denormalised columns on `students` cannot:

      * ONE GUARDIAN, N CHILDREN. A father with three children has his number typed
        three times. He changes it once and two of the three still text the old one.
      * N GUARDIANS, ONE CHILD. Mother, father and an uncle who does the school run
        are three different people with three different relationships to the child,
        and the columns hold exactly one.
      * ACROSS CAMPUSES. A group running a boys' and a girls' school has parents with
        a child in each. They are one person and must sign in once.
      * NO EMAIL. The staff identity surface is keyed on a globally unique email
        address. A large share of guardians in the target market have none, and a
        placeholder address per parent would be both a lie and a second identity.

RESPONSIBILITY
    Four tables: the global guardian IDENTITY (who may sign in), the per-organization
    guardian RECORD (who a school group holds on file), the child LINK (who this
    person is to which student), and the OTP ledger.

INTERACTIONS
    * `guardian_students.student_id` -> `students.id`
    * `sessions.guardian_identity_id` -> `guardian_identities.id`; guardians share
      the staff session table, and therefore its rotation and reuse detection.
    * `modules/guardians/service.py` (staff registry) and `auth_service.py` (login).

=============================================================================
IDENTITY IS GLOBAL, THE GUARDIAN RECORD IS TENANT-SCOPED
=============================================================================
    This is the same split `auth/models.py` makes for staff, for the same two
    reasons, and it is the central design decision of this module.

      1. A CHICKEN-AND-EGG PROBLEM AT LOGIN. To evaluate an RLS policy we need
         `app.current_org_id`, which comes from the token. To mint a token we must
         first find the person by phone number. At that moment there is no token, so
         no org, so the GUC is empty -- and a policy comparing against an empty GUC
         matches ZERO rows. An RLS-protected login table makes login structurally
         impossible.

      2. THE HUMAN GENUINELY SPANS ORGANIZATIONS. A parent may have a child at a
         school in group A and another at a school in group B. That is one person,
         one phone, one PIN-free login. Stamping an `organization_id` on their
         identity would force two accounts for one handset.

    So `guardian_identities` carries NO tenant column and is NOT RLS-protected --
    exactly like `users` -- and `guardians` is the tenant-scoped record that points
    at it, exactly like `memberships`. A guardian who signs in and holds records in
    two organizations picks one, and the token names it. Same shape as staff
    multi-membership, same reason.

    WHAT PROTECTS THE UNPROTECTED TABLES: `guardian_identities` is never enumerated
    by any endpoint. It is reachable only by primary key, or by an exact E.164 phone
    match supplied by a caller who is about to have to prove control of that handset.
    `guardian_otp_codes` is looked up only by identity id. Neither is listable.

WHY THE GUARDIAN RECORD IS ORG-SCOPED AND NOT SCHOOL-SCOPED
    Every other academic table here carries a NOT NULL `school_id`. This one does
    not, and the omission is the point: the parent of two children at two campuses is
    ONE record in the group, and duplicating them per campus recreates the problem
    the module exists to solve. Campus reachability is a property of the LINK
    (`guardian_students`, which does carry `school_id`, because a student does), and
    the repository derives "guardians of this school" from those links rather than
    from a column on the person.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum
from app.db.mixins import (
    CreatedAtMixin,
    RequiredSchoolMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.students.models import Student


class GuardianIdentityStatus(StrEnum):
    """Whether this handset may complete a portal login.

    No PENDING state, unlike `UserStatus`. A staff account is created by its own
    human and must prove the address before it works; a guardian identity is created
    by a SCHOOL that already holds the number on the admission form, and the OTP
    itself is the proof of control. A pending state would mean an extra verification
    step before the verification step.
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"  # set by an operator; blocks login without deleting data


class GuardianRelationship(StrEnum):
    """What this person is to this child.

    An enum rather than free text because it drives BEHAVIOUR, not just display:
    which contact a fee reminder goes to first, who may be handed the child at the
    gate, and what a report card salutation says. Free text ("Baba", "Ammi",
    "guardian?") cannot be branched on and cannot be translated.

    OTHER exists so the list never blocks an enrolment; the printed label for it
    comes from `GuardianStudent.relationship_label`.
    """

    FATHER = "father"
    MOTHER = "mother"
    GRANDPARENT = "grandparent"
    SIBLING = "sibling"
    UNCLE = "uncle"
    AUNT = "aunt"
    LEGAL_GUARDIAN = "legal_guardian"
    OTHER = "other"


class GuardianOtpPurpose(StrEnum):
    """Which door a guardian code opens.

    Bound into the digest by `core/otp.py`, so a code issued for one flow is
    cryptographically useless in another. Only one purpose exists today; the enum is
    here because adding the second one later without domain separation is exactly how
    a login code becomes replayable against a "confirm this payment" endpoint.
    """

    PORTAL_LOGIN = "guardian_portal_login"
    PHONE_CHANGE = "guardian_phone_change"


# =============================================================================
# 1. Identity -- global, no tenant column, NOT RLS-protected. See module docstring.
# =============================================================================


class GuardianIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A phone number that can sign in to the parent portal."""

    __tablename__ = "guardian_identities"

    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    """E.164, canonicalised by `core/phone.py` before it ever reaches this column.

    THE UNIQUE INDEX BELOW IS ONLY MEANINGFUL BECAUSE OF THAT NORMALISATION.
    `0300-1234567` and `+92 300 1234567` are the same handset and would otherwise be
    two rows, two portal accounts, and a parent who sees one of their two children.

    20 characters, not 32: E.164 caps at `+` plus 15 digits. A wider column would
    quietly accept the un-normalised input this design depends on rejecting.
    """

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    """As first recorded. Per-organization overrides live on `Guardian.full_name` --
    the same man is "Muhammad Aslam" on one campus's roll and "M. Aslam Khan" on
    another's, and neither school should be able to rewrite the other's records."""

    email: Mapped[str | None] = mapped_column(CITEXT)
    """OPTIONAL, and never an identifier. Many guardians have none, which is the
    reason this surface exists at all. It is a delivery channel and nothing more --
    login is by phone, always. No unique index: two parents sharing one family
    address is common and must not be a conflict."""

    preferred_locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    """Parent-facing messages are the ones most likely to need Urdu or Arabic. Held on
    the identity rather than per organization: it is a property of the reader."""

    status: Mapped[GuardianIdentityStatus] = mapped_column(
        str_enum(GuardianIdentityStatus, name="status"),
        nullable=False,
        default=GuardianIdentityStatus.ACTIVE,
        index=True,
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- OTP abuse protection ----------------------------------------------
    #
    # Mirrors the staff lockout counters, and for the same reason: a 6-digit code is
    # only as strong as the attempt limit around it. These live on the identity, not
    # on the code row, so burning one code and requesting another does not reset the
    # attacker's budget -- which is the obvious bypass of a per-code counter.
    failed_otp_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    guardians: Mapped[list[Guardian]] = relationship(back_populates="identity")

    __table_args__ = (
        # Unique across LIVE rows only, so a number released when a family leaves can
        # be re-registered later -- Pakistani mobile numbers are recycled by carriers,
        # and permanently burning one would lock out a future, unrelated parent.
        Index(
            "uq_guardian_identities_phone_active",
            "phone",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("phone ~ '^\\+[1-9][0-9]{6,14}$'", name="phone_is_e164"),
    )

    @property
    def is_locked(self) -> bool:
        if self.locked_until is None:
            return False
        return self.locked_until > datetime.now(UTC)

    @property
    def can_authenticate(self) -> bool:
        """Every gate at once, so no call site can check three of the four."""
        return (
            self.status is GuardianIdentityStatus.ACTIVE
            and self.deleted_at is None
            and not self.is_locked
        )


# =============================================================================
# 2. The tenant-scoped guardian record
# =============================================================================


class Guardian(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """One organization's record of one guardian. The `membership` analogue."""

    __tablename__ = "guardians"

    identity_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, not CASCADE. An identity is only ever soft-deleted in practice,
        # and a hard delete that silently removed a school's entire parent contact
        # list is not a repair anyone would authorise.
        ForeignKey("guardian_identities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    """This organization's spelling. See `GuardianIdentity.full_name`."""

    registered_school_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL, not the CASCADE that `SchoolScopedMixin` uses. Archiving a campus
        # must not delete a parent who still has a child at the other one -- the
        # record simply stops being attributable to a campus and becomes org-level,
        # which is what it always was.
        ForeignKey("schools.id", ondelete="SET NULL"),
        index=True,
    )
    """Which campus's front office created this record. NOT a scope key.

    =========================================================================
    WHY THIS COLUMN EXISTS AT ALL, GIVEN THE RECORD IS ORG-LEVEL
    =========================================================================
        Campus visibility is derived from the child LINKS -- "this parent has a child
        at my school". That is the right rule and it is the one that survives a parent
        moving between campuses.

        It has exactly one hole, and it is on the happy path: registering a guardian
        and linking them to a child are two requests, and BETWEEN THEM the guardian
        has no links. A school-scoped registrar would create a parent and immediately
        get a 404 reading them back -- the record would be invisible to the person who
        just typed it.

        This column closes that window without widening anything else: a campus sees a
        guardian it registered, plus every guardian with a child at that campus. An
        org-level principal is unaffected and still spans everything.

    NULL for records created by an org-level principal with no campus selected, and
    for any record whose originating campus was later archived. Both mean "org-level",
    and both are correctly invisible to a campus-scoped caller who has no link either.
    """

    cnic: Mapped[str | None] = mapped_column(String(32))
    """National ID as recorded by the school. Free text and NOT unique: formats vary,
    schools mistype them, and a unique index would block a legitimate second
    enrolment over a typo in the first. It exists for gate verification and for
    matching against government reporting, not for identity."""

    occupation: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(500))

    alternate_phone: Mapped[str | None] = mapped_column(String(20))
    """A landline or second handset the office can try. NEVER a login identifier --
    only `GuardianIdentity.phone` is, and only one number per identity can be, or the
    unique index stops meaning one person."""

    portal_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    """Whether THIS organization's records are reachable from the parent portal.

    Per organization, not per identity, and that asymmetry is deliberate: a group
    that has not launched its portal must be able to keep its parents out of ITS data
    without affecting the same person's login at another group. `auth_service`
    therefore filters the selectable contexts on this column rather than refusing the
    login outright."""

    notes: Mapped[str | None] = mapped_column(String(1000))

    identity: Mapped[GuardianIdentity] = relationship(back_populates="guardians")
    links: Mapped[list[GuardianStudent]] = relationship(
        back_populates="guardian",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # One record per person per organization. Without it, two clerks registering
        # the same father a week apart produce two rows, and half his children hang
        # off each -- which is the denormalised state this module replaced.
        #
        # Partial on live rows so a removed guardian can be re-added later.
        Index(
            "uq_guardians_organization_identity_active",
            "organization_id",
            "identity_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


# =============================================================================
# 3. The link -- who this person is to which child
# =============================================================================


class GuardianStudent(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One guardian's relationship to one student.

    CARRIES `school_id` EVEN THOUGH IT IS DERIVABLE from the student. Two reasons,
    both practical: the repository's campus filter (`BaseRepository`) keys on a
    `school_id` column and a link without one would be invisible to a school-scoped
    teacher; and "which guardians belong to this campus" is answered from this table
    alone, without a join, on every attendance-alert run.
    """

    __tablename__ = "guardian_students"

    guardian_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("guardians.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    relationship_type: Mapped[GuardianRelationship] = mapped_column(
        str_enum(GuardianRelationship, name="relationship_type"),
        nullable=False,
        default=GuardianRelationship.OTHER,
    )
    relationship_label: Mapped[str | None] = mapped_column(String(60))
    """Free-text label shown when `relationship_type` is OTHER, e.g. "Step-father".
    The enum stays branchable; the label stays printable."""

    is_primary_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    """Who the school calls FIRST. At most one per student, enforced by the partial
    unique index below rather than by the service, because "who do I ring about this
    child" must have exactly one answer at three in the afternoon and an application
    bug must not be able to produce two."""

    is_emergency_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    can_pickup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    """Authorised to collect the child. Deliberately independent of every other flag:
    a mother abroad is the primary contact and cannot collect; a neighbour may collect
    and must receive no academic data at all. Collapsing these into one "is guardian"
    boolean is how a child gets handed to the wrong adult."""

    receives_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    """Opt-out for THIS child. A parent with four children does not want four
    identical fee reminders, and a separated parent may be entitled to updates about
    one child and not another."""

    can_view_results: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    """Whether the portal shows this child's academic and fee records to this person.
    The pickup-only neighbour above gets `can_pickup=true` and this `false`."""

    guardian: Mapped[Guardian] = relationship(back_populates="links")
    student: Mapped[Student] = relationship()

    __table_args__ = (
        UniqueConstraint("guardian_id", "student_id", name="uq_guardian_students_guardian_student"),
        # AT MOST ONE primary contact per student, over live rows only. A plain
        # UNIQUE(student_id, is_primary_contact) would instead permit one `true` AND
        # one `false`, and forbid a second non-primary guardian entirely -- the
        # opposite of what is wanted.
        Index(
            "uq_guardian_students_primary_per_student",
            "student_id",
            unique=True,
            postgresql_where=text("is_primary_contact IS TRUE AND deleted_at IS NULL"),
        ),
        # The notification fan-out: "every contactable guardian of these students".
        Index(
            "ix_guardian_students_school_id_student_id",
            "school_id",
            "student_id",
        ),
        CheckConstraint(
            "relationship_type <> 'other' OR relationship_label IS NOT NULL",
            name="other_relationship_needs_label",
        ),
    )


# =============================================================================
# 4. The OTP ledger -- global, for the same pre-authentication reason as identity
# =============================================================================


class GuardianOtpCode(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One issued login code. Append-only; consumption is a timestamp, not a delete.

    A TABLE RATHER THAN A COLUMN ON THE IDENTITY. Codes are evidence: "a code was
    requested for this number from this IP at this time" is the record that answers
    an abuse report, and a single overwritten column keeps only the most recent one --
    which is precisely the row an attacker's flood would have overwritten.

    NOT RLS-PROTECTED, because it is read before any tenant is known. It carries no
    tenant column at all: the code authenticates the HUMAN, and which organization
    they then act in is a separate choice made after verification.
    """

    __tablename__ = "guardian_otp_codes"

    identity_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("guardian_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    purpose: Mapped[GuardianOtpPurpose] = mapped_column(
        str_enum(GuardianOtpPurpose, name="purpose"),
        nullable=False,
        default=GuardianOtpPurpose.PORTAL_LOGIN,
    )

    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """HMAC-SHA256 of `purpose|phone|code` under SECRET_KEY -- see `core/otp.py`.
    The plaintext code exists only in memory and in the SMS. A database dump does not
    yield a usable code, because the pepper is not in the database."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    ip: Mapped[str | None] = mapped_column(String(45))

    __table_args__ = (
        # The verify hot path: newest live code for this identity and purpose.
        Index("ix_guardian_otp_codes_identity_purpose", "identity_id", "purpose", "created_at"),
        # The purge job, and the per-day request quota, which counts rows in a window.
        Index("ix_guardian_otp_codes_expires_at", "expires_at"),
    )

    @property
    def is_usable(self) -> bool:
        """Single-use AND time-limited AND under the attempt cap.

        All three, in one place. A cryptographic match on an expired, spent, or
        exhausted code is still a failed authentication, and a call site that checks
        only `consumed_at` is a call site that accepts yesterday's code.
        """
        return (
            self.consumed_at is None
            and self.expires_at > datetime.now(UTC)
            and self.attempts < _MAX_ATTEMPTS_HARD_CEILING
        )


# The model-level backstop for `is_usable`. The configurable limit lives in settings
# and is enforced by the service; this constant exists so the property is never
# accidentally unbounded when read outside a request (a job, a shell, a data fix).
_MAX_ATTEMPTS_HARD_CEILING = 10
