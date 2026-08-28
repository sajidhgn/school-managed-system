# Academic foundation specification

Status: implemented.
Covers: the academic calendar, the curriculum, and the student enrollment ledger.

These three are one document because they are one thing: the dimensions every
deferred academic module indexes into. Attendance, the gradebook, the timetable and
the report card all need to know *which year*, *which subject* and *which section a
student was in at the time*. None of those existed.

---

## 1. Why this slice exists

The students and academics modules shipped before the module checklist in
`IMPLEMENTATION_ROADMAP.md` did — roughly 700 lines each against 4,900 for fees — and
they are the foundation everything else hangs off. Four gaps blocked the next tier:

| Gap | Consequence | Closed by |
| --- | --- | --- |
| No calendar | "168 of 190 school days" needs a year's **bounds**. The free-text `fees.academic_year` string cannot supply them, and three modules parsing `"2026-2027"` independently is three chances to disagree about whether the year starts in March or April. | `academic_years`, `terms` |
| No curriculum | The gradebook and the timetable both index into a subject list that did not exist. | `subjects`, `class_subjects` |
| No history | `students.section_id` says where a child is **now**. Attendance for 12 March needs to know where they were **then** — promote them in April and a `section_id`-only join silently re-files the whole year's attendance under the new grade. | `student_enrollments` |
| No guardians | Three columns on `students` cannot express siblings, a portal login, or two guardians for one child. | **`modules/guardians`** — built separately; see below. |

The guardian aggregate is deliberately **not** part of this slice. A parent portal
needs a global identity spanning campuses plus an OTP surface — a larger design than a
link table, and one that should not be half-built here and reshaped there. The ten
permission codes seeded by this slice's migration still include `guardian:*`, because
the catalog is seeded ahead of its module on purpose (see `rbac/catalog.py`): a
principal can configure who will manage families before the screens exist.

---

## 2. The calendar

### 2.1 `academic_years`

School-scoped, not organization-scoped. A trust running a city and a rural campus
routinely runs two calendars — the rural campus shifts around the harvest,
international branches run September–June against a local April–March. One org-level
calendar would force one of those campuses to record attendance against dates it was
closed. The cost is that a trust with a genuinely shared calendar creates the same
year once per campus: a few seconds of setup, paid once a year, in exchange for not
making the multi-calendar case unrepresentable.

**`is_current` is an explicit flag, not a derived answer.** "The year whose bounds
contain today" is wrong twice a year: during the summer gap no year contains today,
and in the fortnight where a school finalises last year's results while enrolling for
the next, two are legitimately live.

At most one current year per school, enforced by the **partial** unique index
`uq_academic_years_one_current ... WHERE is_current`. A plain unique index on
`(school_id, is_current)` would instead permit exactly one *non*-current year per
school — the opposite of the rule.

Promotion is its own endpoint (`POST /academic-years/{id}/set-current`) rather than a
PATCH field, because promoting one year **demotes another**. A client PATCHing
`is_current: true` would reasonably think it changed one record; it changed two, and
the one it did not name is the one every default in the app reads from.

### 2.2 `terms`

Terms may not overlap within a year, and must fall inside it. Both are enforced in the
service rather than by a PostgreSQL exclusion constraint: the constraint needs
`btree_gist`, and its violation reaches the client as raw constraint text instead of
*"these dates overlap 'Term 1' (12 Jan – 30 Mar)"*.

`sequence` exists for the same reason `SchoolClass.level` does — sorting "Term 1,
Term 10, Term 2" alphabetically is wrong on every report card, and "which term came
before this one?" is arithmetic the gradebook needs.

### 2.3 What the calendar does not own

Holidays and working days. The attendance percentage denominator is "registers
actually submitted", which is correct without a holiday table (see
`docs/modules/attendance.md` §7). A `school_days` table is what a **timetable** needs
and should land with it.

`fees.academic_year` is **not** re-keyed onto `academic_years.id`. That is a data
migration on issued financial records and nothing in this slice needs it.
`AcademicYear.name` uses the identical format, so the two are joinable by label the
day it is worth doing.

---

## 3. The curriculum

`subjects` is a per-school catalog; codes are upper-cased on the way in, because
"math" and "MATH" are the same subject to every human who will read a report card and
a school that ends up with both has a screen showing a subject twice.

`class_subjects` keys the curriculum on the **class**, not the section. "Grade 10
studies Physics" is a curriculum decision; "Grade 10-B's Physics is taught by Mrs Khan"
is a staffing one. Keying on the class states the first fact once instead of once per
section, which is what stops 10-A and 10-B drifting onto different syllabi.
`teacher_id` is therefore the *default* teacher across the grade; per-section
assignment is a timetable concern and lands with the timetable, which owns the
`(section, subject, slot, teacher)` tuple. A `section_id` here now would create a
second, competing answer that the timetable would immediately contradict.

`subject_id` is `ON DELETE RESTRICT`. Deleting a subject a grade still studies would
silently strip it from the curriculum and, once the gradebook lands, orphan its marks.
The service reads the dependents first so the refusal names the grades rather than a
constraint.

`SubjectKind` (`core` / `elective` / `activity`) drives two concrete behaviours rather
than being decoration: the gradebook must not show an elective as missing for a
student who never chose it, and the timetable may schedule two electives into one slot
but never two cores. `activity` is a third value rather than an `is_graded` boolean
because sports and library periods are timetabled and attended but not graded.

---

## 4. The enrollment ledger

`student_enrollments` records one continuous period a student spent in one section.

**`students.section_id` stays.** It is the *head* of this ledger and sits on the hot
path of every roster read; resolving "the open enrollment" on each of them would turn a
column read into a correlated subquery. The service writes both in one transaction, and
nothing may let them disagree.

**Append-mostly, and therefore no `deleted_at`.** A closed enrollment is a historical
fact. Correcting a mis-seated student means closing the wrong row and opening a right
one — the same reasoning that keeps `deleted_at` off `fee_vouchers`. `left_on` is how a
row ends.

Two partial unique indexes carry the invariants:

* `uq_student_enrollments_one_open ... WHERE left_on IS NULL` — one open enrollment per
  student. Two would make "which section is this child in?" ambiguous at the exact
  moment attendance asks it.
* `uq_student_enrollments_roll ... WHERE roll_number IS NOT NULL` — one roll number per
  section per year, while any number of unnumbered enrollments may coexist (a section
  is often seated before it is numbered).

**`roll_number` is not `admission_number`.** The admission number is issued once and
never changes. The roll number is re-assigned every year in register order, is the
number a teacher calls out, and is what a mark sheet sorts by. Conflating them is why
schools end up reading admission numbers aloud at assembly. Numeric rolls sort
numerically everywhere — roll 10 must not precede roll 2.

### 4.1 The ledger is opportunistic

Opening an enrollment needs an academic year, and a school that has not set one up has
none. Refusing to enrol a student until the calendar exists makes the calendar a hard
prerequisite for the most basic action in the product, and breaks every existing
installation on the day this ships.

So `sync_placement` returns `None` instead of raising when there is no current year:
the student is created, seated and on the register, with no history row yet.
`POST /academic-years/{id}/enrollments/backfill` is the catch-up, run once against an
explicit year, and it is why the migration deliberately populated nothing. It is
idempotent — a student who already has an open enrollment is counted and left alone —
so a retry after a timeout is safe.

The cost is that history can start late. That is strictly better than a product that
cannot enrol a student on day one.

### 4.2 Promotion

`POST /students/promote` moves a section's students into a section of the next year.

**Partial success is the contract, not a compromise.** Aborting the whole batch because
one student is already seated in the target — exactly the state a half-finished earlier
run leaves behind — would make the operation impossible to retry, and retrying is the
first thing anyone does after a timeout. Failures come back named in `skipped`; the run
is still one transaction.

Capacity is checked **once for the batch**. Thirty per-student checks would each count
the same section and pass thirty times against one free seat.

`reset_roll_numbers` defaults to true: schools re-number every year in register order,
and keeping last year's numbers leaves gaps wherever a student was held back. When a
kept number collides, the number is dropped rather than the student skipped — an
unnumbered student is on the register and can be numbered by hand, while a skipped one
is not enrolled at all.

`student:promote` is its own permission, marked `dangerous`. Promotion is whole-school,
once-a-year and looks irreversible from the UI — exactly the shape of action that
should require an explicit grant rather than riding along with "edit a student".

---

## 5. Audit events

`academic_year.created` / `.updated` / `.deleted` / `.activated`;
`term.created` / `.updated` / `.deleted`;
`subject.created` / `.updated` / `.deleted`;
`class_subject.added` / `.updated` / `.removed`;
`student.enrolled` / `.transferred` / `.enrollment_closed` / `.promoted`.

The calendar rows carry `before`/`after` because moving a year's boundary silently
restates every attendance percentage and report card quoted against it, and *"why did
last term's figures change?"* is asked months later.

Enrollment events use `entity_type = "student"` throughout, deliberately: the question
the trail answers is *"what happened to this child's placement"*, and a trail filtered
by an enrollment-row id cannot answer it.

---

## 6. Retention and deletion

* An academic year with enrollments cannot be deleted. The FK is `RESTRICT`, so the
  database would refuse anyway; the service refuses first so the message names the
  cohort rather than a constraint. Nor can the current year be deleted without first
  making another current.
* Subjects and classes soft-delete; enrollments never do.
* Organization deletion cascades from `organizations`, the GDPR erasure path.

---

## 7. Acceptance tests (release gate)

`backend/tests/integration/test_academic_foundation.py` §1–3 and §5:

1. Only one year can be current; promoting demotes the incumbent.
2. `set-current` is its own transition and moves `/academic-years/current`.
3. A year must end after it starts.
4. Terms may not overlap, and must fall inside their year.
5. A year with enrolled students cannot be deleted.
6. Subject codes are upper-cased and unique per school.
7. A subject a class studies cannot be deleted until it is removed from the curriculum.
8. A subject cannot be added to one class twice.
9. Enrolling a student opens exactly one ledger row.
10. The roster sorts by roll number **numerically**.
11. A transfer closes the previous placement and moves `students.section_id` with it.
12. Promotion moves a section, renumbers, and leaves the closed rows behind as history.
13. Promotion refuses to overfill the target section.
14. Backfill is idempotent.
15. Withdrawing a student closes their placement and drops them from the roster.
16. Two organizations cannot see each other's calendars, rosters or enrollment history.
17. Two campuses in one organization are scoped apart; the org-level principal reads both.
18. Raw cross-tenant `INSERT` is rejected by RLS on all seven tables, as `sms_app`.
