"""Student models -- the Student Information System record.

WHY THIS FILE EXISTS
    The PDF marks "Student Directory CRUD" as Critical and specifies the payload:
    demographics and emergency contacts. The student row is the spine of the rest of
    the product -- attendance, fee vouchers, ID cards, certificates and the global
    search omnibar all read from it.

RESPONSIBILITY
    Define the `Student` entity, its enrollment lifecycle, and the guardian/emergency
    contact fields the PDF calls for.

INTERACTIONS
    * `TenantMixin` -> RLS policy installed by `setup_tenant_table("students")`.
    * `section_id` -> `sections.id` (academics module).
    * Future: attendance, fees and certificate modules all reference `students.id`.

WHY GUARDIAN DETAILS ARE COLUMNS AND NOT A `guardians` TABLE
    A separate table is the textbook-correct model -- one guardian can have several
    children, and normalising avoids duplicating a phone number across siblings. It
    is deliberately deferred: the Critical feature is a directory CRUD, the WhatsApp
    modules need one reachable number per student, and a join table would add a
    write path and a merge UI that nothing in the current scope asks for. When
    parent logins arrive (a guardian signing in to see two children) that is the
    moment to promote this into its own aggregate, and the migration is mechanical.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.academics.models import Section


class StudentStatus(StrEnum):
    """Enrollment lifecycle.

    PENDING is what makes the PDF's "Digital Admissions Form" work: a public
    application lands as PENDING and appears in an admissions queue, without ever
    counting as an enrolled student or appearing in a class register.
    """

    PENDING = "pending"  # applied via the admissions form, not yet accepted
    ACTIVE = "active"  # currently enrolled
    INACTIVE = "inactive"  # temporarily withdrawn (long illness, unpaid fees)
    GRADUATED = "graduated"
    TRANSFERRED = "transferred"  # left for another school


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class Student(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """One enrolled (or applying) student at one school."""

    __tablename__ = "students"

    # --- Identity ----------------------------------------------------------
    admission_number: Mapped[str] = mapped_column(String(32), nullable=False)
    """School-issued roll number. Unique per school, not globally -- two schools
    may legitimately both issue "2024-001"."""

    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)

    # --- Demographics (PDF: "demographics") --------------------------------
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    """`Date`, not `DateTime`: a birthday is a calendar date, and storing it with a
    timezone makes it shift by a day depending on where it is read."""

    gender: Mapped[Gender | None] = mapped_column(str_enum(Gender, name="gender"))
    address: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(500))
    """Used by the ID Card Generator feature."""

    # --- Guardian & emergency contact (PDF: "emergency contacts") ----------
    guardian_name: Mapped[str | None] = mapped_column(String(160))
    guardian_phone: Mapped[str | None] = mapped_column(String(32))
    """The number the WhatsApp absence-alert and fee-reminder features message."""
    guardian_email: Mapped[str | None] = mapped_column(String(320))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(160))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32))

    # --- Enrollment --------------------------------------------------------
    section_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL: dissolving a section must not delete its students. They become
        # unassigned and show up in an "unplaced" filter for the admin to re-seat.
        ForeignKey("sections.id", ondelete="SET NULL"),
        index=True,
    )
    """Nullable by design -- an admitted student may not be placed in a section yet,
    and every PENDING applicant has no section at all."""

    status: Mapped[StudentStatus] = mapped_column(
        str_enum(StudentStatus, name="status"),
        nullable=False,
        default=StudentStatus.ACTIVE,
    )
    enrolled_on: Mapped[date | None] = mapped_column(Date)

    section: Mapped[Section | None] = relationship(back_populates="students")

    __table_args__ = (
        UniqueConstraint(
            "school_id", "admission_number", name="uq_students_school_id_admission_number"
        ),
        # Serves the two hot listings: the section register ("show me everyone in
        # Grade 10-A") and the directory filtered by status. Composite and
        # school-first so the RLS predicate can use the same index.
        Index("ix_students_school_id_section_id", "school_id", "section_id"),
        Index("ix_students_school_id_status", "school_id", "status"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_enrolled(self) -> bool:
        """Whether this student occupies a seat and belongs on a class register."""
        return self.status is StudentStatus.ACTIVE and self.deleted_at is None
