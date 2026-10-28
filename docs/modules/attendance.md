# Attendance module specification

Status: backend slice 1 implemented; analytics (§14) and WhatsApp marking (§15) added.
Depends on: the academic calendar and enrollment ledger described in
`docs/modules/academic-foundation.md`.

This document is the agreed behaviour. It follows the checklist in
`IMPLEMENTATION_ROADMAP.md` §"Guidance for every future school module", and it was
written alongside the schema rather than derived from it.

---

## 1. What this module is, and what it is not

It records **who was in the room**: one register per section per date per period, one
line per student on it.

It is **not** a leave-management system (there is no application-and-approval
workflow — an authorised absence is recorded as `excused` by whoever marks it), not a
biometric or RFID integration (those are input devices that would call
`PATCH /attendance/{id}/entries`, not a different data model), and not a timetable.
It does not decide *whether the school was open* on a given day: see §7.

---

## 2. Deliberate exclusions from slice 1

Each was considered and deferred. None requires a table rewrite to add.

| Excluded | Why, and what it would need |
| --- | --- |
| A holiday / working-days calendar | The percentage denominator is "registers actually submitted", which is correct without one (§7). A `school_days` table is what a *timetable* needs, and it should land with the timetable rather than being half-built here. |
| ~~Absence notifications~~ | **Shipped 2026-10-28** as WhatsApp absence alerts: submitting today's whole-day register queues a one-to-one message to each absent child's guardians, if the campus has turned alerts on. See `docs/modules/whatsapp.md` ("Absence alerts"). No attendance table changed. |
| Leave applications | An approval workflow with its own states and actors. Today a school records the outcome (`excused`), not the request. |
| Staff attendance | Different subject, different table. Staff are `memberships`, not `students`, and conflating them would put a teacher's payroll record behind `student:read`. |
| Auto-marking from a device | Needs an authentication story for the device. The write path it would use already exists. |

---

## 3. Actors and permissions

| Code | Held by default | What it unlocks |
| --- | --- | --- |
| `attendance:read` | teacher, principal | View registers, the daily overview, and both reports. |
| `attendance:mark` | teacher, principal | Open a register, set statuses on a DRAFT, submit it, discard a DRAFT — until the register locks (§3.1). |
| `attendance:amend` | **principal only** | Change a SUBMITTED or locked register, or reopen one. Marked `dangerous`. |

`attendance:mark` and `attendance:amend` are separate for the same reason
`fee:collect` and `fee:void` are separate. **A system where the person who records
absences can also erase them has no attendance record, only an attendance opinion** —
and attendance records are what truancy proceedings, fee concessions and safeguarding
referrals are built on.

Every `attendance:amend` action writes `before`/`after` into `audit_logs` with the
reason the caller supplied. The reason is required, not optional.

### 3.1 The marking window

A register stays open to `attendance:mark` through **the day after its date** — a full
24 hours after the school day it records has ended. From then on it is **locked**,
draft or submitted: opening, marking, submitting or discarding it needs
`attendance:amend`, and a teacher gets `409 ATTENDANCE_LOCKED`. On 24 October, the
registers for 24 and 23 October are open; 22 October's is locked.

Without the lock, "submitted" is the only thing protecting history, and a register
nobody submitted could be rewritten by its teacher weeks later. "Today" is the same UTC
date the rest of the module uses. `locked` is returned on every register and on
`GET /attendance/today`, so the UI never has to work out the window itself.

`attendance:amend` holders can still open a register up to 30 days back. That limit
catches a mistyped date; it is not a permission boundary.

---

## 4. Entities, states and transitions

### 4.1 Register — `attendance_sessions`

One row per `(section_id, session_date, period)`, enforced by a unique constraint.

```
        open (idempotent)          submit
   ∅ ──────────────────────► DRAFT ────────► SUBMITTED
                              │  ▲               │
                     discard  │  └───────────────┘
                              ▼      reopen  (attendance:amend)
                              ∅
```

* **DRAFT** — opened and pre-filled, not yet asserted. Editable with
  `attendance:mark`. Excluded from every report. Discardable.
* **SUBMITTED** — the teacher asserts the register is complete and correct. It now
  feeds reports. Every further change needs `attendance:amend`.

**`period` is NOT NULL, with `0` meaning "whole day."** The natural encoding of
"whole day" is `period = NULL`, and it is a trap: PostgreSQL treats NULLs as distinct
in a unique index, so `UNIQUE (section_id, session_date, period)` would happily accept
the same daily register five times. One honest sentinel beats a partial index plus a
`COALESCE`-based second index and a rule about which applies where.

A whole-day register may not name a subject
(`ck_attendance_sessions_whole_day_has_no_subject`): it covers every lesson, so it is
about no single one.

### 4.2 Register line — `attendance_records`

One row per student per register. `UNIQUE (session_id, student_id)`.

| Status | In the building? | In the denominator? | Credit |
| --- | --- | --- | --- |
| `present` | yes | yes | 1.0 |
| `late` | yes | yes | 1.0 |
| `half_day` | yes | yes | 0.5 |
| `absent` | no | yes | 0.0 |
| `excused` | no | **no** | — |

Five values, not two, because each changes a downstream number:

* **`late`** counts as attended for the percentage a report card prints, but is what a
  punctuality warning is issued from. Folding it into `present` loses the warning;
  folding it into `absent` triggers absence alerts for children who are in the
  building.
* **`excused`** is an absence the school authorised. It leaves the denominator
  entirely — an authorised absence is neither attendance nor a failure to attend, and
  counting it either way misreports the child.
* **`half_day`** is standard in this market for a child collected after the morning
  session.

These rules are stated once, on the `AttendanceStatus` enum (`is_present`, `credit`,
`counts_toward_attendance`), so the student report and the section report cannot
drift apart.

---

## 5. The three decisions that shape the schema

### 5.1 A register is a row, not an implicit grouping

The obvious schema is one flat table keyed `(student, date, status)`. It cannot answer
the question a head teacher actually asks — *"which classes have not submitted
today?"* — because an unmarked register and a register of thirty present students are
both, in a flat table, an absence of rows.

Making the register a first-class row with a `status` turns "not taken" into a fact
that can be listed, chased and reported on. `GET /attendance/today` is that list, and
`session_id: null` is that distinction.

### 5.2 Absence is recorded, not inferred

Every student on the roster gets a row, including the present ones. Storing only
absences halves the table and makes *"was Ali marked present, or was Ali simply
forgotten?"* unanswerable — which is the one question a parent disputing a fine will
ask.

Opening a register pre-fills every student `present`; the teacher flips the
exceptions. A DRAFT register is therefore **complete by construction**, so the only
question left is whether it has been asserted.

The honest cost: an abandoned register leaves thirty `present` rows. That is why draft
rows never reach a report, and why `discard` exists.

### 5.3 Neither table has `deleted_at`

Same reasoning as `fee_vouchers` and `fee_payments`. A submitted register is corrected
by an audited amendment, never by deletion. A *draft* is hard-deleted, because a draft
was never asserted and is not history.

---

## 6. Required fields and uniqueness

| Table | NOT NULL | Unique |
| --- | --- | --- |
| `attendance_sessions` | `organization_id`, `school_id`, `section_id`, `academic_year_id`, `session_date`, `period`, `status` | `(section_id, session_date, period)` |
| `attendance_records` | `organization_id`, `school_id`, `session_id`, `student_id`, `status` | `(session_id, student_id)` |

Checks: `period >= 0`; `period > 0 OR subject_id IS NULL`;
`minutes_late IS NULL OR minutes_late >= 0`.

`minutes_late` is cleared whenever the status moves away from `late`, so
"absent, 15 minutes late" is unrepresentable rather than merely discouraged.

---

## 7. School-year behaviour, and the denominator question

`academic_year_id` is denormalised onto the register rather than derived from its
date, so a term report is an indexed equality filter instead of a range scan over
every register ever taken.

The year is resolved from the register's **date**, not from whichever year is current
(`AcademicCalendarService.resolve_for_date`). Back-filling last June's register must
not restate this year's figures.

**The percentage denominator is "registers this student appeared on that were
SUBMITTED, minus excused ones."** Not "school days", which would require a holiday
calendar this module deliberately does not own. The consequence is worth stating
plainly: a day nobody took a register does not count against anyone. That is the
correct behaviour — a school that failed to mark a class has not established that
anyone was absent — and `GET /attendance/today` exists so those days get chased on
the day rather than discovered at report time.

---

## 8. Bulk operations

* **Open** writes one record per roster entry in one transaction.
* **Mark** is partial: `PATCH /attendance/{id}/entries` carries only the changed
  students. A teacher marks four absentees out of thirty, on a phone, on school wifi;
  thirty requests — or four that can each fail independently and leave the register
  half-changed — is the wrong unit.
* An amendment writes **one audit row per changed student**, not one per batch. *"Who
  changed Ali's 12 March absence to present, and why"* is the question the trail is
  read with, and a row saying "8 records amended" cannot answer it.

---

## 9. Reports

| Endpoint | Answers |
| --- | --- |
| `GET /attendance/today` | Which sections have submitted, are in draft, or have not started. |
| `GET /attendance/students/{id}/summary` | One student's rate over a date range, with the five status counts. |
| `GET /attendance/sections/{id}/report` | One section day by day, plus an average. |

Both reports take an explicit date range rather than a term id. A term is one range a
caller might want; "since the parents' evening" and "the last 30 days" are others, and
a term-only API cannot express them. The frontend resolves a term to its dates.

`percentage` is **null, not 0.0**, when nothing countable exists. A student nobody has
marked yet has no attendance rate, and 0% would put a disciplinary-looking figure
against them.

---

## 10. Plan limits

Attendance consumes no plan capacity. There is no 402 path in this module. It is
metered by student count, which `max_students` already caps.

---

## 11. Audit events

`attendance_session.opened`, `.submitted`, `.reopened`, `.discarded`, and
`attendance_record.amended`.

`submitted` and `amended` are separate actions rather than one "changed" because they
answer different questions and are held by different permissions. *"Who marked today's
register?"* is routine; *"who rewrote a register that was already submitted?"* is the
one an investigation starts from, and it must not be buried among thousands of the
former.

---

## 12. Retention, export, soft delete and restoration

* Registers and records are retained for the life of the organization. They are
  minors' records with legal weight; there is no automatic purge.
* Organization deletion removes them via `ON DELETE CASCADE` from `organizations`,
  which is the GDPR erasure path.
* There is no soft delete and therefore no restoration. A draft is discarded
  permanently; a submitted register is amended, never removed.
* Export is via the two report endpoints. A CSV/PDF register export is frontend work
  and needs no schema change.

---

## 13. Acceptance tests (release gate)

Implemented in `backend/tests/integration/test_academic_foundation.py` §4–5:

1. Opening a register pre-fills the roster `present`.
2. Opening the same register twice returns the first — idempotent.
3. A whole-day register cannot name a subject.
4. Attendance cannot be recorded for a future date.
5. Marking is partial; students not named keep their status.
6. Submitting twice is a conflict.
7. A student outside the register cannot be marked into it.
8. `attendance:mark` alone cannot change or reopen a SUBMITTED register.
9. An amendment requires a reason and writes one audit row per changed student.
10. A submitted register cannot be discarded; a draft can.
11. The daily overview distinguishes "not marked" from "fully present".
12. `excused` leaves the denominator; `half_day` counts half; `late` counts present.
13. Draft registers reach no report.
14. Two organizations cannot see each other's registers (404, never 403).
15. Two campuses in one organization are scoped apart, while the org-level principal
    still reads both.
16. Raw cross-tenant `INSERT` is rejected by RLS on both tables, as `sms_app`.

---

## 14. Analytics

Read-only views over the same two tables, in `analytics.py` (service) and
`AttendanceAnalyticsRepository` (SQL). No schema change. Gated on
`attendance:read`. A teacher without `class:view_all` sees only their own sections
and the children seated in them now; a principal sees the campus (an org-level
principal with no campus open sees every campus RLS allows).

| Endpoint | Answers |
| --- | --- |
| `GET /attendance/analytics` | Per section: rate vs the previous period of equal length, status counts, students on roll, registers submitted and in draft, marking coverage, today's register state, and at-risk count. Plus a campus summary, a daily trend, a weekday pattern, the at-risk list (worst 100, with each child's current run of consecutive absences), and a headline of today / this month / last month / academic year so far. Query: `from_date`, `to_date` (default: the last 30 days), `class_id`, `threshold` (default 75), `min_sessions` (default 5). |
| `GET /attendance/students` | One row per active student: today's register state and status, this month, last month, and an "overall" range (default: the academic year so far). Paginated; `q` matches a name or admission number anywhere, or a roll number exactly; `sort_by` is `overall` (default, worst first), `this_month`, `previous_month`, `name`, `admission_number`, `roll_number` or `class`. Filters: `class_id`, `section_id`. |
| `GET /attendance/students/{id}/calendar` | One student day by day, with a rate per month and over the range (default: the academic year so far). A draft day carries no status. |

The rules, on top of §4.2 and §7:

* **The whole-day register (`period = 0`) is the unit.** Lesson registers answer a
  different question, and counting eight of them as a day would weight that day
  eight times. A school that marks only per lesson sees empty analytics.
  `GET /attendance/students/{id}/summary` predates this and counts every register,
  so for a school that marks both kinds the two can differ.
* **"School days" is a proxy:** a date on which at least one whole-day register was
  submitted among the sections the caller may see. There is no holiday calendar
  (§2). Marking coverage is measured against it, so a day nobody marked at all is
  invisible here. The daily overview is what catches that, on the day.
* **The headline is fixed to the calendar**, not to the selected range, so "this
  month" does not move when someone changes the date picker.
* **Today's status shows only once the register is submitted.** A draft is
  pre-filled `present` (§5.2), so showing it would report a child present on a
  register nobody has confirmed. `today_register` separates "not marked yet" from
  "present".
* **At risk** means below `threshold` with at least `min_sessions` counted
  registers in the range, so one absence on the first day is not 0% at the top of
  the list.
* A student's rate counts every register the child is on (by current section for a
  teacher's bound), so a child who changed section mid-month shows the same figure
  everywhere.
* Ranges over 366 days are refused (`DATE_RANGE_TOO_LONG`); a reversed range is
  `INVALID_DATE_RANGE`, as for the other reports.

Frontend: the dashboard shows the overall rate (this month vs last month, today,
year so far) and every class ranked, for both principals and teachers.
`/attendance/analytics` is the full class view, `/attendance/students` the
per-student table, and each student's page links to their month calendar.

Tests: `backend/tests/integration/test_attendance_analytics.py`.

---

## 15. Marking by WhatsApp

Teachers can also submit the whole-day register by messaging the school's WhatsApp
number (`Nursery-A absent 12, 13, 15`). The agent shows the matched names back and
submits only on **OK**, through the same `open_session` → `mark` → `submit` calls as
the web register, so §3's separation of duties holds unchanged. See
[attendance-agent.md](attendance-agent.md).
