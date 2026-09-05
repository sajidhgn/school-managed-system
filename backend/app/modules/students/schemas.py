"""Student API contracts.

Note what is absent from `StudentCreate`: `school_id` (taken from the JWT) and
`status` for the public admissions path (forced to PENDING by the service). Both
omissions are deliberate -- a client that could set either would be able to write
into another tenant, or self-approve an application.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import EmailStr, Field

from app.common.schemas import BaseSchema
from app.modules.students.models import Gender, StudentStatus


class StudentBase(BaseSchema):
    """Fields common to create and update, so validation rules are defined once."""

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    date_of_birth: date | None = None
    gender: Gender | None = None
    address: str | None = Field(default=None, max_length=1000)
    photo_url: str | None = Field(default=None, max_length=500)

    guardian_name: str | None = Field(default=None, max_length=160)
    guardian_phone: str | None = Field(default=None, max_length=32)
    guardian_email: EmailStr | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=160)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)


class StudentCreate(StudentBase):
    """Staff-facing creation: the student is enrolled immediately."""

    admission_number: str = Field(min_length=1, max_length=32, examples=["2026-001"])
    section_id: UUID | None = None
    status: StudentStatus = StudentStatus.ACTIVE
    enrolled_on: date | None = None


class StudentAdmissionRequest(StudentBase):
    """Public admissions form payload (PDF: "Digital Admissions Form").

    Has no `admission_number`, no `section_id` and no `status`: an applicant cannot
    assign themselves a roll number, place themselves in a class, or admit
    themselves. The service generates the number and forces status to PENDING.
    """

    school_id: UUID = Field(description="Which school is being applied to.")


class StudentUpdate(BaseSchema):
    """PATCH: every field optional, omission means "leave unchanged"."""

    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    date_of_birth: date | None = None
    gender: Gender | None = None
    address: str | None = Field(default=None, max_length=1000)
    photo_url: str | None = Field(default=None, max_length=500)
    guardian_name: str | None = Field(default=None, max_length=160)
    guardian_phone: str | None = Field(default=None, max_length=32)
    guardian_email: EmailStr | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=160)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    section_id: UUID | None = None
    status: StudentStatus | None = None
    enrolled_on: date | None = None


class FeeStandingFilter(StrEnum):
    """How the students list may be narrowed by what a family owes.

    A three-state filter rather than a `pending: bool`, because the third state is the
    one an accountant actually asks for -- "who can I clear for the trip" is a real
    question and `pending=false` does not express it in a way the URL survives.

    OVERDUE is a strict subset of PENDING: money that is late is also money owed.
    """

    PENDING = "pending"
    """Any live challan still carrying a balance, due or not."""

    OVERDUE = "overdue"
    """Only balances past their due date."""

    CLEAR = "clear"
    """Nothing outstanding -- INCLUDING students who have never been billed.

    Deliberately not called "paid": a child enrolled last week with no challan yet
    has paid nothing, and would be the most confusing possible entry in a list
    labelled that way. The question this answers is "does this family owe us
    anything", and for them the answer is no.
    """


class ExamResultFilter(StrEnum):
    """How the students list may be narrowed by one exam's outcomes.

    All three states require the student to have been MARKED in the chosen exam:
    an unmarked student is "no data", not a pass -- filtering happens mid-marking,
    and half-entered sheets must not read as half the school passing.
    """

    PASSED = "passed"
    """Marked, missed nothing, and cleared every paper that declares a pass line."""

    FAILED = "failed"
    """Below the pass line on at least one paper that declares one. Papers with
    no `pass_marks` cannot fail anyone -- no line, no verdict."""

    ABSENT = "absent"
    """Missed at least one paper. Separate from FAILED because the office does
    different things with the two lists: absentees get a re-sit, not a retake."""


class StudentRead(BaseSchema):
    id: UUID
    admission_number: str
    first_name: str
    last_name: str
    full_name: str
    date_of_birth: date | None
    gender: Gender | None
    address: str | None
    photo_url: str | None
    guardian_name: str | None
    guardian_phone: str | None
    guardian_email: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    section_id: UUID | None
    class_name: str | None
    section_name: str | None
    """Where this child actually sits, resolved for display.

    `section_id` alone is unreadable, and a UUID in a table column is a lookup the
    reader has to do by hand. Both are nullable because an APPLICANT has no seat yet
    -- an admission is accepted before a section is chosen, and that gap is a real
    state the list has to render rather than a missing value to hide.
    """
    status: StudentStatus
    enrolled_on: date | None
    created_at: datetime
    updated_at: datetime


class StudentDues(BaseSchema):
    """What one student owes, under whichever fee filter was applied.

    THE AMOUNT IS RELATIVE TO THE FILTER, and that is the point. Under
    `fees=overdue` this is the LATE money only, not the full balance -- a family that
    owes 13,000 of which 6,500 is past due appears as 6,500 on an overdue list.
    Showing the full balance there would make every row look worse than it is, and an
    office chasing a number the parent has not yet been asked for loses the argument.
    """

    amount: Decimal
    currency: str

    overdue_amount: Decimal
    """How much of `amount` is past its due date. Zero means owed but not yet late.

    Carried so the table can COLOUR the row: this project's palette reserves
    saturated colour for status, and red is documented to mean something is wrong.
    Owing money is not wrong -- being late is -- so red has to be driven by this
    field and not merely by the presence of a balance.

    It also earns its place under the `pending` filter, where the list is a MIXTURE
    of late and not-yet-due families. Without the split, every row on that screen
    would look identical and the colour would distinguish nothing.
    """

    periods: list[str]
    """Which billing periods make up the amount, oldest debt first.

    FREE TEXT, straight from `fee_vouchers.period_label` -- "2026-08", but equally
    "Term 1" or "Annual", because monthly, termly and annual schools all exist. The
    frontend prettifies the `YYYY-MM` shape into a month and prints anything else
    verbatim; parsing it as a date here would turn a termly school's challan into a
    crash or, worse, a wrong month.
    """


class StudentListRow(StudentRead):
    """A student as the DIRECTORY shows them: the record plus what they owe.

    Separate from `StudentRead` rather than two more nullable fields on it, because
    `dues` cannot be populated anywhere else. `create`, `get` and `update` answer
    "what is this record", have no fee filter to be relative to, and would carry the
    field as a permanent null that every caller learns to ignore. Same split, and the
    same reason, as `AttendanceSessionRead` and `AttendanceSessionDetail`.
    """

    dues: StudentDues | None
    """Null unless the request applied a `fees` filter -- which requires `fee:read`.

    That is deliberately the ONLY route by which an amount reaches this endpoint. A
    student list that always carried balances would hand every holder of
    `student:read` -- the seeded teacher role among them -- the money owed by each
    child's family, which is a considerably larger disclosure than the one-bit filter
    that is already gated.
    """

    exam_result: StudentExamResult | None = None
    """Null unless the request named an `exam` -- which requires `grade:read`.
    Same discipline as `dues`: marks reach the directory only through the gated
    filter that asked for them."""


class StudentExamResult(BaseSchema):
    """One student's totals in whichever exam the directory was filtered by.

    Totals are over the papers MARKED for this student, mirroring the result
    sheet: an unmarked paper is missing data, not a zero. Absent papers count
    their maximum (the sitting happened; the student scored nothing on it).
    """

    total_obtained: Decimal
    total_max: int
    percentage: Decimal
    failed_papers: int
    """Papers below their declared pass line. Zero on papers with no line."""
    absent_papers: int


# `StudentListRow` refers to `StudentExamResult` before it is defined; the
# `from __future__ import annotations` turns that into a forward reference, and
# this call resolves it. Same dance as `ClassSummary` in the academics schemas.
StudentListRow.model_rebuild()


class AdmissionResponse(BaseSchema):
    """Deliberately thin. The public form must not echo back the stored record --
    that would turn the endpoint into a way to probe another school's data."""

    id: UUID
    admission_number: str
    status: StudentStatus
    detail: str = "Application received. The school will contact you."


# ---------------------------------------------------------------------------
# Enrollment history
# ---------------------------------------------------------------------------


class EnrollmentRead(BaseSchema):
    id: UUID
    student_id: UUID
    academic_year_id: UUID
    class_id: UUID
    section_id: UUID | None
    roll_number: str | None
    enrolled_on: date
    left_on: date | None
    is_promotion: bool
    notes: str | None
    created_at: datetime


class EnrollmentPlacement(BaseSchema):
    """Seat a student in a section for a year, closing whatever came before.

    `class_id` is absent on purpose: a section belongs to exactly one class, so
    accepting both would let a caller submit a pair that disagree, and the service
    would have to pick a winner. It is derived from the section.
    """

    section_id: UUID
    academic_year_id: UUID | None = Field(
        default=None,
        description="Defaults to the school's current academic year.",
    )
    roll_number: str | None = Field(
        default=None,
        max_length=16,
        description="Omit to take the next free number in the section.",
    )
    effective_date: date | None = Field(
        default=None, description="Defaults to today. The day the new placement starts."
    )
    notes: str | None = Field(default=None, max_length=2000)


class PromotionRequest(BaseSchema):
    """Move a whole section up into the next year (PDF: end-of-year rollover)."""

    from_section_id: UUID
    to_section_id: UUID
    to_academic_year_id: UUID
    effective_date: date | None = Field(
        default=None, description="Defaults to the target year's start date."
    )
    student_ids: list[UUID] | None = Field(
        default=None,
        max_length=500,
        description=(
            "Restrict the promotion to these students. Omit to promote everyone "
            "currently seated in the source section -- the usual case. Supplying a "
            "subset is how a school holds a student back a year."
        ),
    )
    reset_roll_numbers: bool = Field(
        default=True,
        description=(
            "Re-number the promoted students 1..N in the target section. Schools "
            "re-number every year in register order; keeping last year's numbers "
            "leaves gaps wherever a student was held back or left."
        ),
    )


class PromotionSkip(BaseSchema):
    """One student the promotion could not move, and why.

    Returned rather than raised. A promotion is a bulk action over a whole section,
    and aborting the entire run because one student is already seated in the target
    would make the feature unusable exactly when it is retried after a partial
    failure.
    """

    student_id: UUID
    admission_number: str
    full_name: str
    reason: str


class PromotionResult(BaseSchema):
    promoted: int
    skipped: list[PromotionSkip]
    from_section_id: UUID
    to_section_id: UUID
    to_academic_year_id: UUID


class EnrollmentBackfillResult(BaseSchema):
    """What `POST /academic-years/{id}/enrollments/backfill` did.

    Exists because the migration that created `student_enrollments` deliberately did
    not populate it: an enrollment needs an academic year, and no school had one
    until it created one. This is that catch-up, run once per school against an
    explicit year.
    """

    academic_year_id: UUID
    opened: int
    already_enrolled: int
    unplaced: int
    """Active students with no section. They get no enrollment row -- a placement
    that names no section is not a placement -- and are counted so the registrar
    knows how many students still need seating."""


class SectionRosterEntry(BaseSchema):
    """One line of a class register, in roll order."""

    student_id: UUID
    admission_number: str
    full_name: str
    roll_number: str | None
    status: StudentStatus
    photo_url: str | None
    guardian_phone: str | None
