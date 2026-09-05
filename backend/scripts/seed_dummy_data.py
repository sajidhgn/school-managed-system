"""Fill an organization with believable demo data, for looking at the app.

WHY THIS SCRIPT EXISTS
    `python -m app.cli seed --demo` builds ONE organization from scratch with two
    campuses and a handful of invitations. That is a fixture for the invitation flow,
    not a populated product: every list in the app renders its empty state, so there
    is no way to see whether a table paginates, whether a fee summary reads sensibly,
    or whether the sidebar's campus modules look right with real names in them.

    This fills an EXISTING organization instead -- the one you already sign in as --
    up to a target number of campuses, each with classes, sections, students, staff,
    pending invitations, a custom role, and a term's worth of fee vouchers in mixed
    states of payment.

IT IS SAFE TO RE-RUN, AND IT NEVER TOUCHES WHAT IS ALREADY THERE
    Everything is topped UP rather than created blind: campuses to `--schools`,
    classes to `--classes`, staff to `--staff`. A level or a class name you already
    use is left alone and skipped, a fee head with an existing code is reused, and
    students are only generated for classes this run created. So a second run adds
    nothing, and a campus you have started organising by hand keeps exactly what you
    put there.

WHY IT WRITES MODELS DIRECTLY
    A thousand students through the HTTP API is thousands of round trips and an
    entitlement check per row. These are ORM inserts inside one transaction per
    campus, and the plan counters are recomputed at the end with the same
    `reconcile_usage()` the scheduled job uses -- which is exactly the drift-repair
    path it exists for. The counters therefore end up correct, not merely untouched.

    The trade-off is that no audit rows are written for the generated data, because
    nobody actually performed those actions. The audit screen shows the real history
    of what you did.

USAGE
    uv run python scripts/seed_dummy_data.py --org-slug cambridge-int
    uv run python scripts/seed_dummy_data.py --org-slug cambridge-int --schools 5 \
        --classes 10 --min-students 20 --max-students 30
    make seed-dummy org=cambridge-int
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import random
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import app.db.registry  # noqa: F401  (side effect: registers every mapper so FKs resolve)
from app.cli import reconcile_usage
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.db.session import dispose_engine, init_engine, session_scope
from app.modules.academics.models import (
    ClassSubject,
    SchoolClass,
    Section,
    Subject,
    SubjectKind,
)
from app.modules.auth.models import User, UserStatus
from app.modules.fees.models import (
    FeeHead,
    FeeLineType,
    FeePayment,
    FeePaymentStatus,
    FeeRecurrence,
    FeeStructure,
    FeeStructureItem,
    FeeStructureStatus,
    FeeVoucher,
    FeeVoucherItem,
    PaymentMethod,
    StationeryCategory,
    StationeryItem,
    StationeryUnit,
    VoucherStatus,
)
from app.modules.invitations.models import Invitation, InvitationStatus
from app.modules.rbac.catalog import SCHOOL_SCOPED_CODES
from app.modules.rbac.models import Membership, MembershipStatus, Role, RolePermission
from app.modules.rbac.provisioning import provision_school
from app.modules.students.models import Student, StudentStatus
from app.modules.tenancy.models import Organization, School, SchoolStatus

# Deterministic, so two runs of the same command produce the same names and a
# re-run after a wipe looks like the same school rather than a new one.
RNG = random.Random(20260827)

# --- Name pools. Pakistani names, because that is who this product is for. ---
FIRST_M = [
    "Ahmed", "Bilal", "Danish", "Faizan", "Hamza", "Imran", "Junaid", "Kamran",
    "Mustafa", "Noman", "Omar", "Rehan", "Saad", "Talha", "Usman", "Waleed",
    "Yasir", "Zain", "Abdullah", "Haris",
]
FIRST_F = [
    "Aisha", "Bushra", "Dua", "Fatima", "Hina", "Iqra", "Javeria", "Kinza",
    "Laiba", "Mahnoor", "Nimra", "Rabia", "Sana", "Tania", "Urooj", "Warda",
    "Yusra", "Zainab", "Amna", "Hafsa",
]
LAST = [
    "Ahmed", "Ali", "Butt", "Chaudhry", "Farooq", "Gilani", "Hussain", "Iqbal",
    "Javed", "Khan", "Malik", "Nawaz", "Qureshi", "Raza", "Sheikh", "Tariq",
    "Usmani", "Zafar", "Rashid", "Siddiqui",
]

CITIES = [
    ("Lahore", "LHR"), ("Karachi", "KHI"), ("Islamabad", "ISB"),
    ("Faisalabad", "FSD"), ("Multan", "MUX"), ("Peshawar", "PEW"),
    ("Sialkot", "SKT"), ("Gujranwala", "GUJ"),
]

FEE_HEADS = [
    ("TUITION", "Tuition fee", FeeRecurrence.MONTHLY, 1),
    ("ADMISSION", "Admission fee", FeeRecurrence.ONE_TIME, 2),
    ("TRANSPORT", "Transport", FeeRecurrence.MONTHLY, 3),
    ("EXAM", "Examination fee", FeeRecurrence.TERM, 4),
]

# What the campus SELLS, as opposed to what it charges. Priced per unit; the quantity
# lands on the structure line, which is the whole reason these are not fee heads.
STATIONERY_ITEMS = [
    ("COPY-100", "Copy (Register, 100 pages)", StationeryCategory.NOTEBOOK,
     StationeryUnit.PIECE, Decimal(60), 1),
    ("PENCIL-HB", "Pencil (HB)", StationeryCategory.STATIONERY,
     StationeryUnit.DOZEN, Decimal(240), 2),
    ("BOOK-SET", "Course book set", StationeryCategory.BOOK,
     StationeryUnit.SET, Decimal(4200), 3),
    ("UNIFORM-SHIRT", "Uniform shirt", StationeryCategory.UNIFORM,
     StationeryUnit.PIECE, Decimal(950), 4),
]

# How many of each every student in a seeded class is billed. Only the copies and
# pencils: a book set on every term's challan would look like a bug, and it is
# exactly the mistake `include_stationery` exists to prevent.
STATIONERY_ON_STRUCTURE = {"COPY-100": Decimal(4), "PENCIL-HB": Decimal(1)}

# The subject catalogue every campus gets: code -> (name, kind, weekly periods).
# Codes and names match what a Pakistani school calls them; weekly periods are
# what the timetable generator will read, weighted the way schools weight them
# (English and Mathematics heaviest, activities once or twice a week).
SUBJECT_CATALOGUE: dict[str, tuple[str, SubjectKind, int]] = {
    "ENG": ("English", SubjectKind.CORE, 6),
    "URD": ("Urdu", SubjectKind.CORE, 5),
    "MATH": ("Mathematics", SubjectKind.CORE, 6),
    "ISL": ("Islamiat", SubjectKind.CORE, 3),
    "GK": ("General Knowledge", SubjectKind.CORE, 4),
    "SCI": ("General Science", SubjectKind.CORE, 5),
    "SST": ("Social Studies", SubjectKind.CORE, 4),
    "PAK": ("Pakistan Studies", SubjectKind.CORE, 3),
    "PHY": ("Physics", SubjectKind.CORE, 4),
    "CHEM": ("Chemistry", SubjectKind.CORE, 4),
    "BIO": ("Biology", SubjectKind.CORE, 4),
    "CS": ("Computer Science", SubjectKind.ELECTIVE, 3),
    "ART": ("Art & Drawing", SubjectKind.ELECTIVE, 2),
    "PE": ("Physical Education", SubjectKind.ACTIVITY, 2),
    "LIB": ("Library", SubjectKind.ACTIVITY, 1),
}


def curriculum_for(level: int) -> list[str]:
    """Which of the catalogue a grade actually studies.

    Follows the shape of a Pakistani school: General Knowledge in the infants,
    General Science and Social Studies through middle school, the split sciences
    plus Pakistan Studies from Grade 9 (matric). Levels above 10 keep the matric
    set -- a hand-made "Grade 11" gets a sensible curriculum, not an empty one.
    """
    codes = ["ENG", "URD", "MATH", "ISL", "PE"]
    if level <= 3:
        codes += ["GK", "ART", "LIB"]
    elif level <= 5:
        codes += ["SCI", "SST", "ART", "LIB"]
    elif level <= 8:
        codes += ["SCI", "SST", "CS", "ART"]
    else:
        codes += ["PHY", "CHEM", "BIO", "PAK", "CS"]
    return codes


ACADEMIC_YEAR = "2026-2027"
PERIOD = "Term 1"


def full_name() -> tuple[str, str, str]:
    """(first, last, gender) — gender drives the first-name pool, not the reverse."""
    gender = RNG.choice(("male", "female"))
    first = RNG.choice(FIRST_M if gender == "male" else FIRST_F)
    return first, RNG.choice(LAST), gender


def slugify(value: str) -> str:
    return "-".join("".join(c if c.isalnum() else " " for c in value.lower()).split())


async def ensure_schools(session, org: Organization, target: int) -> list[School]:
    """Top the organization up to `target` campuses. Returns all of them."""
    existing = list(
        (
            await session.execute(
                select(School).where(School.deleted_at.is_(None)).order_by(School.created_at)
            )
        )
        .scalars()
        .all()
    )
    made = 0
    for index in range(len(existing), target):
        city, code_stem = CITIES[index % len(CITIES)]
        name = f"{org.name.rstrip('.')} {city}"
        code = f"{code_stem}{index + 1:02d}"
        school = School(
            id=uuid4(),
            organization_id=org.id,
            name=name,
            code=code,
            slug=slugify(name),
            city=city,
            email=f"{code.lower()}@{slugify(org.name)}.edu.pk",
            phone=f"+92-4{index}-{RNG.randint(1000000, 9999999)}",
            address=f"{RNG.randint(1, 400)} Main Boulevard, {city}",
            status=SchoolStatus.ACTIVE,
        )
        session.add(school)
        await session.flush()
        # The same roles a real campus gets: teacher and accountant. `principal` is
        # org-level and already exists once for the whole organization.
        await provision_school(session, organization_id=org.id, school_id=school.id)
        existing.append(school)
        made += 1
    return existing, made


async def seed_subjects(session, org: Organization, school: School) -> dict[str, int]:
    """Give one campus its subject catalogue, taught to EVERY class it has.

    Self-contained (queries its own classes, roles and existing rows) so it runs
    both inside a full populate and alone via `--subjects-only` -- "Grade 6
    studies nothing" is wrong however the class got there. Topped up like
    everything else in this script: a subject whose code or name you already use
    blocks that slot, and a (class, subject) pair you assigned is left alone.
    """
    counts = {"subjects": 0, "class subjects": 0}

    subjects = list(
        (
            await session.execute(select(Subject).where(Subject.school_id == school.id))
        ).scalars().all()
    )
    subject_codes = {s.code for s in subjects}
    subject_names = {s.name for s in subjects}
    for code, (subject_name, kind, _periods) in SUBJECT_CATALOGUE.items():
        if code in subject_codes or subject_name in subject_names:
            continue
        subject = Subject(
            id=uuid4(),
            organization_id=org.id,
            school_id=school.id,
            code=code,
            name=subject_name,
            kind=kind,
        )
        session.add(subject)
        subjects.append(subject)
        counts["subjects"] += 1
    await session.flush()
    subjects_by_code = {s.code: s for s in subjects}

    # Default teachers come from the campus's real teacher accounts. ~70% of
    # rows get one; the rest stay open, because an unstaffed subject is a real
    # state the curriculum screen shows.
    teacher_role = (
        await session.execute(
            select(Role).where(Role.school_id == school.id, Role.code == "teacher")
        )
    ).scalar_one_or_none()
    teacher_ids: list[UUID] = []
    if teacher_role is not None:
        teacher_ids = list(
            (
                await session.execute(
                    select(Membership.user_id).where(
                        Membership.school_id == school.id,
                        Membership.role_id == teacher_role.id,
                        Membership.status == MembershipStatus.ACTIVE,
                        Membership.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
        )

    all_classes = list(
        (
            await session.execute(
                select(SchoolClass).where(
                    SchoolClass.school_id == school.id,
                    SchoolClass.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )
    # Soft-deleted pairs included on purpose: the (class, subject) unique
    # constraint is not partial, so a deleted row still blocks a re-insert.
    assigned = {
        (row.class_id, row.subject_id)
        for row in (
            await session.execute(
                select(ClassSubject).where(ClassSubject.school_id == school.id)
            )
        ).scalars().all()
    }
    for cls in all_classes:
        for code in curriculum_for(cls.level):
            subject = subjects_by_code.get(code)
            if subject is None or (cls.id, subject.id) in assigned:
                continue
            session.add(
                ClassSubject(
                    id=uuid4(),
                    organization_id=org.id,
                    school_id=school.id,
                    class_id=cls.id,
                    subject_id=subject.id,
                    teacher_id=(
                        RNG.choice(teacher_ids)
                        if teacher_ids and RNG.random() < 0.7
                        else None
                    ),
                    weekly_periods=SUBJECT_CATALOGUE[code][2],
                )
            )
            counts["class subjects"] += 1
    await session.flush()
    return counts


async def populate_school(
    session,
    org: Organization,
    school: School,
    *,
    class_count: int,
    min_students: int,
    max_students: int,
    staff_per_school: int,
) -> dict[str, int]:
    """Top one campus up. Anything already present is left exactly as it is."""
    counts = {"classes": 0, "sections": 0, "students": 0, "staff": 0,
              "invitations": 0, "roles": 0, "vouchers": 0, "payments": 0,
              "subjects": 0, "class subjects": 0}

    roles = {
        r.code: r
        for r in (
            await session.execute(select(Role).where(Role.school_id == school.id))
        ).scalars().all()
    }

    # --- A custom role, because every real school invents one ----------------
    if "head_of_year" not in roles:
        head_of_year = Role(
            id=uuid4(),
            organization_id=org.id,
            school_id=school.id,
            code="head_of_year",
            name="Head of Year",
            description="Runs one year group: attendance, grades and pastoral care.",
            is_system=False,
            is_editable=True,
            permissions_version=1,
        )
        session.add(head_of_year)
        await session.flush()
        session.add_all(
            RolePermission(role_id=head_of_year.id, organization_id=org.id, permission_code=code)
            for code in sorted(
                SCHOOL_SCOPED_CODES
                & {
                    "member:read", "school:read", "student:read", "student:update",
                    "class:read", "teacher:read", "attendance:read", "attendance:mark",
                    "grade:read", "grade:manage", "timetable:read", "audit:read",
                }
            )
        )
        counts["roles"] += 1

    # --- Classes and sections ------------------------------------------------
    #
    # Both `level` and `name` are unique per campus, so a class you created by hand
    # blocks that slot. Skipping it is the point: your "3rd" at level 1 stays, and
    # this fills the levels around it.
    existing_classes = (
        await session.execute(select(SchoolClass).where(SchoolClass.school_id == school.id))
    ).scalars().all()
    taken_levels = {c.level for c in existing_classes}
    taken_names = {c.name for c in existing_classes}

    classes: list[SchoolClass] = []
    for level in range(1, class_count + 1):
        name = f"Grade {level}"
        if level in taken_levels or name in taken_names:
            continue
        cls = SchoolClass(
            id=uuid4(),
            organization_id=org.id,
            school_id=school.id,
            name=name,
            level=level,
        )
        session.add(cls)
        classes.append(cls)
        counts["classes"] += 1
    await session.flush()

    sections: dict[UUID, list[Section]] = {}
    for cls in classes:
        sections[cls.id] = []
        for letter in ("A", "B"):
            section = Section(
                id=uuid4(),
                organization_id=org.id,
                school_id=school.id,
                class_id=cls.id,
                name=letter,
                capacity=30,
            )
            session.add(section)
            sections[cls.id].append(section)
            counts["sections"] += 1
    await session.flush()

    # --- Students ------------------------------------------------------------
    admission_seq = 0
    students_by_class: dict[UUID, list[Student]] = {}
    for cls in classes:
        students_by_class[cls.id] = []
        for index in range(RNG.randint(min_students, max_students)):
            admission_seq += 1
            first, last, gender = full_name()
            guardian_first, _, _ = full_name()
            # A small tail of non-active students, so the status filter and the
            # entitlement counter both have something to show.
            status = StudentStatus.ACTIVE
            roll = RNG.random()
            if roll > 0.94:
                status = StudentStatus.INACTIVE
            elif roll > 0.90:
                status = StudentStatus.PENDING
            student = Student(
                id=uuid4(),
                organization_id=org.id,
                school_id=school.id,
                section_id=sections[cls.id][index % 2].id,
                admission_number=f"{school.code}-{admission_seq:04d}",
                first_name=first,
                last_name=last,
                gender=gender,
                date_of_birth=date(2026 - 5 - cls.level, RNG.randint(1, 12), RNG.randint(1, 28)),
                guardian_name=f"{guardian_first} {last}",
                guardian_phone=f"+92-3{RNG.randint(10, 49)}-{RNG.randint(1000000, 9999999)}",
                guardian_email=f"{first.lower()}.{last.lower()}{admission_seq}@example.pk",
                address=(
                    f"House {RNG.randint(1, 900)}, "
                    f"Block {RNG.choice('ABCDEFG')}, {school.city}"
                ),
                status=status,
                enrolled_on=date(2026, 4, 1) + timedelta(days=RNG.randint(0, 60)),
            )
            session.add(student)
            students_by_class[cls.id].append(student)
            counts["students"] += 1
    await session.flush()

    # --- Staff: real accounts that can actually sign in ----------------------
    #
    # Counted against what the campus already has, so a re-run tops up to `--staff`
    # rather than adding another full set every time.
    already_staff = (
        await session.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.school_id == school.id, Membership.deleted_at.is_(None))
        )
    ).scalar_one()
    #
    # One shared hash for every generated account. Hashing is deliberately slow, and
    # doing it once instead of forty keeps this script to seconds rather than a
    # minute -- they all share a password anyway, and it is printed at the end.
    shared_hash = hash_password(STAFF_PASSWORD)
    for index in range(already_staff, staff_per_school):
        first, last, _ = full_name()
        role = roles["teacher"] if index < staff_per_school - 1 else roles["accountant"]
        email = f"{first.lower()}.{last.lower()}.{school.code.lower()}{index}@example.pk"
        user = User(
            id=uuid4(),
            email=email,
            full_name=f"{first} {last}",
            locale="en",
            password_hash=shared_hash,
            status=UserStatus.ACTIVE,
            email_verified_at=datetime.now(UTC),
            mfa_enabled=False,
        )
        session.add(user)
        await session.flush()
        session.add(
            Membership(
                id=uuid4(),
                organization_id=org.id,
                user_id=user.id,
                school_id=school.id,
                role_id=role.id,
                status=MembershipStatus.ACTIVE,
                is_primary=True,
                joined_at=datetime.now(UTC),
            )
        )
        counts["staff"] += 1

    # --- Curriculum ----------------------------------------------------------
    await session.flush()  # so the staff created just above join the teacher pool
    for key, value in (await seed_subjects(session, org, school)).items():
        counts[key] += value

    # --- Pending invitations -------------------------------------------------
    already_invited = (
        await session.execute(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.school_id == school.id,
                Invitation.status == InvitationStatus.PENDING,
            )
        )
    ).scalar_one()
    for index in range(already_invited, 2):
        first, last, _ = full_name()
        session.add(
            Invitation(
                id=uuid4(),
                organization_id=org.id,
                school_id=school.id,
                email=f"pending.{first.lower()}{index}.{school.code.lower()}@example.pk",
                full_name=f"{first} {last}",
                role_id=roles["teacher"].id,
                # Never a usable token: this is a hash of a value nothing knows, so
                # the row shows up on the invitations screen and cannot be accepted.
                token_hash=uuid4().hex + uuid4().hex,
                status=InvitationStatus.PENDING,
                expires_at=datetime.now(UTC) + timedelta(days=RNG.randint(2, 12)),
            )
        )
        counts["invitations"] += 1

    # --- Fees ----------------------------------------------------------------
    heads = list(
        (
            await session.execute(select(FeeHead).where(FeeHead.school_id == school.id))
        ).scalars().all()
    )
    have = {h.code for h in heads}
    for code, name, recurrence, order in FEE_HEADS:
        if code in have:
            continue
        head = FeeHead(
            id=uuid4(),
            organization_id=org.id,
            school_id=school.id,
            code=code,
            name=name,
            recurrence=recurrence,
            is_refundable=code == "ADMISSION",
            is_active=True,
            sort_order=order,
        )
        session.add(head)
        heads.append(head)

    # The stationery catalog, seeded the same way and for the same reason: the fee
    # screens are unreadable without something in them.
    articles = list(
        (
            await session.execute(
                select(StationeryItem).where(StationeryItem.school_id == school.id)
            )
        ).scalars().all()
    )
    stocked = {a.code for a in articles}
    for code, name, category, unit, price, order in STATIONERY_ITEMS:
        if code in stocked:
            continue
        article = StationeryItem(
            id=uuid4(),
            organization_id=org.id,
            school_id=school.id,
            code=code,
            name=name,
            category=category,
            unit=unit,
            unit_price=price,
            is_active=True,
            sort_order=order,
        )
        session.add(article)
        articles.append(article)
    await session.flush()

    voucher_seq = 0
    receipt_seq = 0
    # Vouchers for the lower years only. Enough for the fee screens to look real
    # without minting one per student across the whole school.
    for cls in classes[:4]:
        structure = FeeStructure(
            id=uuid4(),
            organization_id=org.id,
            school_id=school.id,
            class_id=cls.id,
            academic_year=ACADEMIC_YEAR,
            name=f"{cls.name} — {ACADEMIC_YEAR}",
            status=FeeStructureStatus.ACTIVE,
        )
        session.add(structure)
        await session.flush()

        # Tuition scales with the year group; the rest are flat.
        prices = {
            "TUITION": Decimal(4000 + cls.level * 250),
            "ADMISSION": Decimal(15000),
            "TRANSPORT": Decimal(2500),
            "EXAM": Decimal(1800),
        }
        for head in heads:
            session.add(
                FeeStructureItem(
                    id=uuid4(),
                    organization_id=org.id,
                    school_id=school.id,
                    structure_id=structure.id,
                    line_type=FeeLineType.FEE,
                    head_id=head.id,
                    # A fee line is one unit priced at its own amount. Storing the
                    # identity rather than leaving the columns empty is what lets
                    # every total sum `amount` alone.
                    quantity=Decimal(1),
                    unit_price=prices[head.code],
                    amount=prices[head.code],
                )
            )

        stationery_lines = [
            (article, STATIONERY_ON_STRUCTURE[article.code])
            for article in articles
            if article.code in STATIONERY_ON_STRUCTURE
        ]
        for article, quantity in stationery_lines:
            session.add(
                FeeStructureItem(
                    id=uuid4(),
                    organization_id=org.id,
                    school_id=school.id,
                    structure_id=structure.id,
                    line_type=FeeLineType.STATIONERY,
                    stationery_item_id=article.id,
                    quantity=quantity,
                    # Frozen here, not read live at generation: a structure is a
                    # price list, so a later reprice must not restate it.
                    unit_price=article.unit_price,
                    amount=quantity * article.unit_price,
                )
            )

        # One voucher per ACTIVE student in the class, for this term.
        billable = [h for h in heads if h.code in ("TUITION", "TRANSPORT", "EXAM")]
        subtotal = sum(prices[h.code] for h in billable) + sum(
            quantity * article.unit_price for article, quantity in stationery_lines
        )
        for student in students_by_class[cls.id]:
            if student.status is not StudentStatus.ACTIVE:
                continue
            voucher_seq += 1
            issue = date(2026, 4, 5)
            due = issue + timedelta(days=20)

            roll = RNG.random()
            if roll < 0.55:
                status, paid = VoucherStatus.PAID, subtotal
            elif roll < 0.75:
                status, paid = VoucherStatus.PARTLY_PAID, (subtotal / 2).quantize(Decimal("1"))
            elif roll < 0.90:
                status, paid = VoucherStatus.ISSUED, Decimal(0)
            else:
                status, paid = VoucherStatus.OVERDUE, Decimal(0)

            voucher = FeeVoucher(
                id=uuid4(),
                organization_id=org.id,
                school_id=school.id,
                student_id=student.id,
                structure_id=structure.id,
                voucher_number=f"{school.code}-V{voucher_seq:05d}",
                academic_year=ACADEMIC_YEAR,
                period_label=PERIOD,
                issue_date=issue,
                due_date=due,
                status=status,
                currency="PKR",
                subtotal=subtotal,
                discount_total=Decimal(0),
                total=subtotal,
                paid_total=paid,
                issued_at=datetime(2026, 4, 5, tzinfo=UTC),
                paid_at=datetime(2026, 4, 18, tzinfo=UTC) if status is VoucherStatus.PAID else None,
            )
            session.add(voucher)
            counts["vouchers"] += 1

            for order, head in enumerate(billable, start=1):
                session.add(
                    FeeVoucherItem(
                        id=uuid4(),
                        organization_id=org.id,
                        school_id=school.id,
                        voucher_id=voucher.id,
                        line_type=FeeLineType.FEE,
                        head_id=head.id,
                        line_name=head.name,  # the snapshot
                        quantity=Decimal(1),
                        unit_price=prices[head.code],
                        amount=prices[head.code],
                        discount_amount=Decimal(0),
                        sort_order=order,
                    )
                )

            # Offset so stationery prints below every fee line, matching what
            # `FeeService._create_voucher` does at real generation time.
            for order, (article, quantity) in enumerate(stationery_lines, start=1001):
                session.add(
                    FeeVoucherItem(
                        id=uuid4(),
                        organization_id=org.id,
                        school_id=school.id,
                        voucher_id=voucher.id,
                        line_type=FeeLineType.STATIONERY,
                        stationery_item_id=article.id,
                        line_name=article.name,
                        unit_label=article.unit.value,
                        quantity=quantity,
                        unit_price=article.unit_price,
                        amount=quantity * article.unit_price,
                        discount_amount=Decimal(0),
                        sort_order=order,
                    )
                )

            if paid > 0:
                receipt_seq += 1
                session.add(
                    FeePayment(
                        id=uuid4(),
                        organization_id=org.id,
                        school_id=school.id,
                        voucher_id=voucher.id,
                        receipt_number=f"{school.code}-R{receipt_seq:05d}",
                        amount=paid,
                        currency="PKR",
                        method=RNG.choice(
                            (
                                PaymentMethod.CASH,
                                PaymentMethod.BANK_TRANSFER,
                                PaymentMethod.CARD,
                                PaymentMethod.ONLINE,
                            )
                        ),
                        received_on=issue + timedelta(days=RNG.randint(1, 25)),
                        status=FeePaymentStatus.RECORDED,
                    )
                )
                counts["payments"] += 1

    await session.flush()
    return counts


STAFF_PASSWORD = "Demo-Passphrase-9271"


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    init_engine(settings)

    try:
        # Find the organization with no tenant bound: this is a maintenance script,
        # and the whole point is that it has not signed in as anybody.
        async with session_scope(platform_admin=True) as session:
            org = (
                await session.execute(
                    select(Organization).where(
                        Organization.slug == args.org_slug,
                        Organization.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if org is None:
                print(f"No organization with slug {args.org_slug!r}.")
                slugs = (
                    (await session.execute(select(Organization.slug))).scalars().all()
                )
                print(f"Known slugs: {', '.join(sorted(slugs)) or '(none)'}")
                return 1
            org_id, org_name = org.id, org.name

        totals: dict[str, int] = {}
        async with session_scope(org_id) as session:
            org = (await session.execute(select(Organization))).scalar_one()
            # `--subjects-only` never creates campuses: target 0 makes
            # `ensure_schools` a plain read of what exists.
            schools, made = await ensure_schools(
                session, org, 0 if args.subjects_only else args.schools
            )
            print(f"{org_name}: {len(schools)} campus(es) ({made} created)")

        for school in schools:
            async with session_scope(org_id, school_id=school.id) as session:
                counts = (
                    await seed_subjects(session, org, school)
                    if args.subjects_only
                    else await populate_school(
                        session,
                        org,
                        school,
                        class_count=args.classes,
                        min_students=args.min_students,
                        max_students=args.max_students,
                        staff_per_school=args.staff,
                    )
                )
                for key, value in counts.items():
                    totals[key] = totals.get(key, 0) + value
                added = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
                print(f"  {school.name}: {added or 'nothing to add'}")

        # The ORM inserts bypassed the incremental counters every write path
        # maintains, so recompute them from the source tables — the same repair the
        # scheduled job performs.
        async with session_scope(org_id) as session:
            await reconcile_usage(session, org_id)
        print("usage counters recomputed")

        if totals:
            print("\ntotals: " + ", ".join(f"{v} {k}" for k, v in totals.items() if v))
            if totals.get("staff"):
                print(f"generated staff sign in with: {STAFF_PASSWORD}")
        return 0
    finally:
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org-slug", required=True, help="e.g. cambridge-int")
    parser.add_argument("--schools", type=int, default=5, help="target campus count")
    parser.add_argument("--classes", type=int, default=10, help="classes per campus")
    parser.add_argument("--min-students", type=int, default=20)
    parser.add_argument("--max-students", type=int, default=30)
    parser.add_argument("--staff", type=int, default=6, help="staff accounts per campus")
    parser.add_argument(
        "--subjects-only",
        action="store_true",
        help="only seed the subject catalogue and per-class curriculum; "
        "touch nothing else and create no campuses, classes or people",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
