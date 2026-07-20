"""Student API contracts.

Note what is absent from `StudentCreate`: `school_id` (taken from the JWT) and
`status` for the public admissions path (forced to PENDING by the service). Both
omissions are deliberate -- a client that could set either would be able to write
into another tenant, or self-approve an application.
"""

from __future__ import annotations

from datetime import date, datetime
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
    status: StudentStatus
    enrolled_on: date | None
    created_at: datetime
    updated_at: datetime


class AdmissionResponse(BaseSchema):
    """Deliberately thin. The public form must not echo back the stored record --
    that would turn the endpoint into a way to probe another school's data."""

    id: UUID
    admission_number: str
    status: StudentStatus
    detail: str = "Application received. The school will contact you."
