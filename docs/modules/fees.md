# Fees module specification

Status: slice 1 shipped — heads → structures → vouchers → payments, manual
collection with a printable challan. Extended 2026-08-28 with the stationery
catalog: articles the school sells, priced per unit and charged by quantity on the
same challan (§5.1b, §5.5).

Slice 2 shipped 2026-08-28 and closes five of the nine deferrals §2 recorded:
concession schemes and per-student discounts (§5.2c), negotiated per-student rates
(§5.2b), one-off charges on a draft challan (§5.5b), automatic late fees (§5.6), and
the running student ledger with arrears carry-forward (§5.7). Two deferrals remain
open and both are blocked on something outside this module — see §2.

The printed challan was rebuilt 2026-09-25 to the ruled bank-counter layout schools
in this market already use, with the payment accounts and the copy list moved onto
the campus row (`schools.challan_design`) and a combined print that puts a term of
months on one page (§9, §9.1).
Last updated: 2026-09-25

`IMPLEMENTATION_ROADMAP.md` ("Guidance for every future school module") requires an
agreed module specification before any academic module is built, and lists the
minimum it must document. This file is that document for fees. It is the source of
truth for fee behaviour; the core spec (`educloud-core-spec.md`) remains the source
of truth for tenancy, RBAC, billing and everything else the foundation owns.

## 1. What this module is, and what it is not

**Is:** how a school bills its students and records what they paid. Fee heads, a
stationery catalog, per class fee structures, generated per-student vouchers
(challans), manually recorded payments, receipts, and a printable challan.

A school does not only *charge* — it also *sells*: copies, pencils, books, uniform.
Those reach the parent on the same challan as tuition, because a parent receives one
bill and pays it at one counter. So they are lines on the same voucher, discriminated
by `line_type`, not a second document (§5.5).

**Is not:** an inventory system. `stationery_items` owns the price, because the price
is what lands on a challan. Stock levels, suppliers, purchase orders and stocktakes
belong to an inventory module that does not exist yet. A half-inventory that
decrements a counter with no receiving path or wastage record produces a number the
store keeper knows is wrong and the finance office believes.

**Is not:** the SaaS subscription the school pays *us*. That is the `billing`
module, which is a different money flow between different parties, denominated in a
different currency, settled through a payment gateway. The two never share a table,
a permission, or an invoice number sequence. `invoice:read` governs what the school
owes EduCloud; `fee:read` governs what a parent owes the school.

## 2. What was deferred, and where it stands

Slice 1 deferred nine things, each with a note claiming it would need no table
rewrite. Slice 2 tested that claim on five of them: every change was additive, and no
existing column changed meaning. The table below is the running record.

### Closed in slice 2

| Was excluded | How it landed |
| --- | --- |
| Scholarships / concession policies | `fee_concessions` holds the named scheme; a `DISCOUNT` arrangement points at one or carries its own rate (§5.2c). The `discount_amount` column that had been on `fee_voucher_items` since slice 1, zero on every row, is now written. No voucher schema change, as predicted. |
| Per-student amount overrides (a negotiated or legacy tuition rate) | An `OVERRIDE` mode on the same table, restating a class line's amount rather than adding one (§5.2b). |
| One-off charges (fines, re-exam, breakage) | `PUT /fees/vouchers/{id}/charges`, mirroring the stationery path exactly: draft-only, idempotent by head (§5.5b). |
| Automatic late fees / fines | `fee_late_fee_policies` holds the rule; the run mints each fine as its OWN challan rather than rewriting the overdue one, which is the only way to add a penalty without breaking Rule 1 (§5.6). |
| Arrears carry-forward and a running ledger | `student_ledger_entries`, append-only, plus `fee_vouchers.arrears_brought_forward` to snapshot what a challan was printed with. The carried balance is PRINTED and deliberately NOT billed (§5.7). |

### Still open

| Excluded | Why, and what unblocks it |
| --- | --- |
| Online payment by parents | Blocked on the same open product decision as SaaS billing (JazzCash / Easypaisa / Stripe). Nothing in this module blocks it: `PaymentMethod.ONLINE` and the `reference` column exist, and a gateway callback records a payment through the same `record_payment` staff use — which now also writes the ledger entry, so the parent-facing balance follows for free. |
| Sibling / family grouping | Needs a guardian aggregate. `students/models.py` defers it until parent logins arrive, and a `guardians` module is in flight; sibling remission should be built on it rather than on a surname match, which is what every school's first attempt does and what breaks on the first blended family. |

### Excluded by design, not deferred

| Excluded | Why it stays out |
| --- | --- |
| Stationery stock and suppliers | `stationery_items` is a price list. An inventory module links to it by id and adds its own columns to its own tables; nothing here changes. |
| Charging stationery to an already-issued challan | Refused by design — an issued bill is never rewritten (§5.5). The charge goes on the student's next challan, which is how a school's own ledger already treats it. |

## 3. Actors

| Actor | Typical role | What they do here |
| --- | --- | --- |
| Principal | `principal` (org-level) | Everything, including voiding vouchers and reversing payments. |
| Accountant | `accountant` (school-scoped) | Defines heads and structures, generates and issues vouchers, records payments, prints challans. **Cannot** void or reverse. |
| Teacher | `teacher` | Nothing. Fees are deliberately absent from the teacher default set. |
| Parent / student | — | No access. There is no portal in this slice; the challan reaches them on paper. |

**Separation of duties is the reason `fee:void` is its own permission.** The person
who records money coming in must not be the person who can make a record of money
disappear. An accountant who mis-keys a receipt asks a principal to reverse it; that
reversal is audited with both identities. Granting `fee:void` to an accountant is a
supported customer choice — it is simply not the default.

## 4. Permissions

Five codes, all `SCHOOL` scope, all in `modules/rbac/catalog.py`.

| Code | Grants | Dangerous | In `accountant` default |
| --- | --- | --- | --- |
| `fee:read` | View heads, stationery, structures, vouchers, payments, summaries, challan PDFs | No | Yes |
| `fee:manage` | Create/edit/delete fee heads, stationery items, structures, and per-student fee arrangements | Yes | Yes |
| `fee:issue` | Generate vouchers in bulk, issue them, charge stationery to a draft | No | Yes |
| `fee:collect` | Record a payment and issue a receipt | No | Yes |
| `fee:void` | Void a voucher, reverse a payment | Yes | **No** |

`fee:read` and `fee:manage` already existed in the catalog as wired-but-unimplemented
codes. `fee:issue`, `fee:collect` and `fee:void` are new; seeding them is additive
and `make seed` upserts the catalog, so existing custom roles are unaffected and
existing `accountant` roles are re-provisioned with the new defaults.

**Stationery added no sixth code, and that is a decision.** The catalog is
`fee:manage` because it answers exactly the question fee heads answer — what this
campus may put on a challan. Charging an article to a student's draft is `fee:issue`
because it answers the other one — who is charged what. A separate `stationery:*`
family would mean a school hiring a store keeper had to discover and grant two more
codes to reproduce the access their accountant already had, for no boundary the
existing five do not already draw.

Every route names its permission through `require(...)`. No route in this module is
reachable without one.

## 5. Entities, states and transitions

### 5.1 Fee head — `fee_heads`

A billable line a school charges for: Tuition, Transport, Examination, Admission.

- Unique on `(school_id, code)`. Two campuses may both have `TUITION`.
- `recurrence` (`monthly` | `term` | `annual` | `one_time`) is descriptive metadata
  for the person building a structure. It does not drive generation — the operator
  chooses the period at generation time, because real schools bill the annual
  admission fee inside the August monthly challan rather than on its own.
- Soft-deleted. A head referenced by any structure item cannot be deleted; the
  refusal names the count. Deactivate (`is_active = false`) instead — it disappears
  from pickers while existing structures keep working.

### 5.1b Stationery item — `stationery_items`

An article the school sells by quantity: a copy, a pencil, a book, a uniform shirt.

- Unique on `(school_id, code)`, exactly like a fee head. Two campuses sell their own
  copies at their own prices.
- `category` (`book` | `notebook` | `stationery` | `uniform` | `sports` | `other`)
  groups the picker and nothing else. Coarse on purpose: a school stocks two hundred
  SKUs and reports on six groupings of them. Anything finer belongs in the name.
- `unit` (`piece` | `dozen` | `pack` | `set` | `pair` | `ream`) is printed beside the
  quantity on the challan, because "Pencil × 2" is ambiguous and expensive — two
  pencils and two dozen pencils differ by twelve, and the parent finds out at the
  counter.
- `unit_price` is the **current** price of one unit. Repricing it is safe and needs
  no ceremony because it is not retroactive: every structure line froze the price it
  was added at, and every challan line froze the price it sold at.
- Soft-deleted, and deletion is refused while **any structure line or challan line**
  charges it. Stricter than the fee-head rule, which only counts structures: a head
  reaches a challan solely through a structure, but an article can also be charged
  ad-hoc straight onto a draft voucher.

**Why this is not just another fee head.** A head is a flat amount per period —
Tuition is 5,000 whether the student attends twenty days or two. An article is a unit
price and a count, and the count differs per student in the same class. "Copies: 480"
as a head cannot answer the only question anyone asks about that line. Modelling it
as one would mean a head per (article, quantity) pair, and a school with forty
articles would need four hundred heads by December.

### 5.2 Fee structure — `fee_structures` + `fee_structure_items`

What one class is charged for one academic year.

```
DRAFT ──activate──> ACTIVE ──archive──> ARCHIVED
  │                    │
  └────archive─────────┘
```

- Unique on `(school_id, class_id, academic_year)`. One structure per class per
  year; changing next year's fees means a new structure, not an edit.
- Items are of two kinds, discriminated by `line_type`:
  - a **fee** line is `(head_id, amount)`, with `quantity = 1` and
    `unit_price = amount`;
  - a **stationery** line is `(stationery_item_id, quantity, unit_price)`, with
    `amount = quantity × unit_price`.

  Every total in the module therefore sums `amount` alone and never has to ask which
  kind of line it is adding. A `CHECK` makes any other combination — a stationery
  line pointing at a head, a fee line with no head — unrepresentable.
- Uniqueness is two **partial** indexes: `(structure_id, head_id)` where `head_id`
  is not null, and `(structure_id, stationery_item_id)` where that is not null. A
  plain unique constraint would silently stop guaranteeing anything once the columns
  became nullable, because PostgreSQL treats every NULL as distinct.
- A stationery line **freezes its unit price** at the moment it is added. A structure
  is a price list — "this is what Grade 10 is charged in 2026-2027" — so reading the
  catalog's live price at generation time would let a January reprice silently change
  what an operator approved in August. Picking up a new price is an explicit,
  audited act: add the line again.
- Items are editable while `DRAFT` or `ACTIVE`, frozen once `ARCHIVED`. Editing an
  `ACTIVE` structure never rewrites history, because vouchers snapshot their amounts
  at generation (§5.3).
- Only an `ACTIVE` structure can generate vouchers. `DRAFT` exists so a structure can
  be built over several sittings without becoming billable halfway through.
- Archiving is refused while the structure has vouchers in `DRAFT` — issue or void
  them first, so no voucher is orphaned mid-flight.

### 5.2b Student fee assignment — `student_fee_assignments`

Where **one student** departs from what their class is charged.

Students in a class are not all billed the same thing: one takes the bus, one
boards, one walks. This table records only the **differences**:

| Mode | Meaning | Value it carries |
| --- | --- | --- |
| `added` | A head this student pays that their class does not — hostel, transport, lunch | `amount` required. The rate is the point: transport is priced by route, so two students on the same bus routinely pay different numbers |
| `excluded` | A head the class is charged that this student is not — the child who walks | Nothing |
| `override` | A head the class IS charged, at a rate agreed for this child alone — the legacy family, the negotiated sibling rate | `amount` required. **Replaces** the class amount; it never adds a line |
| `discount` | A concession against a head this student is billed for | Exactly one of `concession_id`, `amount` or `percent` |

**`override` replaces, and contributes nothing when there is nothing to replace.** If
the class structure prices no such head, the override is inert — it does not quietly
become an `added` line. The two are different facts ("Ali pays a different tuition"
vs "Ali pays for a bus nobody else does"), and collapsing them would let a mis-picked
head start billing a family for a service the child never took.

**The order the four resolve in is the design, not an implementation detail.**
`_effective_lines()` applies `override`, then `excluded`, then `added`, then
`discount`, and each step is chosen against a way of getting it wrong that nobody
would notice. The last one is the one that costs money: *"half of what this child
pays"* computed against the class list price bills the wrong number for every child
on a negotiated rate — and bills it **invisibly**, because the challan still shows a
plausible-looking 50%.

- Unique on `(student_id, academic_year, head_id)`. A student cannot be both charged
  and not charged for transport, nor added twice at two rates.
- `amount` is required on `added` and forbidden on `excluded`, enforced by a CHECK
  **and** a Pydantic model validator so the error names the field. An excluded head
  is **absent** from the challan, not zero — a "Transport 0.00" line is a question a
  parent phones about.
- Soft-deleted. "Ali came off the bus in March" is a fact somebody will be asked
  about, and a row that vanishes cannot answer it.
- `fee:manage`, not `fee:issue`. Putting a child on the bus at 2,000 a month is a
  pricing decision that recurs — the same kind of decision as adding a line to a
  structure. A clerk trusted to run the monthly billing must not be able to quietly
  attach a 4,000 hostel charge to a bill.

**Why a delta table and not a per-student fee plan.** The obvious alternative — give
every student their own complete list of heads and amounts — was rejected. Two days
decide it:

- **A new admission arrives mid-term.** With a delta the child is billed correctly
  the moment they are placed in a section, because the class structure already says
  what Grade 10 pays. With per-student plans somebody must type six lines first, and
  the day they forget, the child is billed *nothing* and nobody notices until
  year-end.
- **Tuition rises 8%.** One edit to the structure and everyone on the standard rate
  follows. Per-student plans mean five hundred edits, and the missed ones are
  invisible because there is no "standard" left to compare against.

So a student with **no rows here is billed their class's structure exactly** — the
overwhelmingly common case, costing nothing to express. And "what does Grade 10 pay?"
stays answerable, because there is still a fact to answer it with.

**Keyed on the student and the year, not on the structure.** "Ali takes the bus in
2026-2027" is a fact about Ali and that year. It survives him moving from section A
to B, or being promoted mid-year — both change which structure bills him, neither
should take him off the bus. It does *not* roll into the next academic year, because
bus routes and hostel places are renewed annually.

**One merge, two callers.** `FeeService._effective_lines()` applies the assignments
to the class base, and both `GET /fees/students/{id}/fee-profile` (the preview) and
generation call it. A preview showing 6,500 against a challan billing 8,500 is worse
than no preview at all, because the operator checked and was told the wrong thing.
Generation fetches every student's assignments for a run in **one** query, not one
per student — the batch is up to 500 students and the cost would otherwise grow with
the size of the school.

### 5.2c Concession — `fee_concessions`

A **named** remission a family is put on: Staff Child 50%, Merit 25%, Sibling 1,000
off. `kind` is `percent` or `amount`; `value` is read against it, held to 0–100 by a
CHECK when it is a percentage.

**Why the rate lives on the scheme and not on each child.** The same argument that
makes the class structure the base for billing makes a policy the base for
concessions. A school does not award four hundred unrelated discounts — it operates
five or six schemes and puts families on them. Recording the rate per child means:

- *"Staff remission goes from 40% to 50%"* is four hundred edits, and the ones missed
  are invisible, because there is no scheme left to compare a child against.
- *"How many children are on merit scholarship, and what does it cost us this year?"*
  has no answer. That is a governing-body question, asked every year, and a pile of
  ad-hoc percentages cannot answer it. The list endpoint returns `student_count` per
  scheme for exactly this reason.

Ad-hoc remissions stay possible — a `discount` row can carry its own `amount` or
`percent` — because the genuinely one-off case (a family in crisis, agreed by the
principal in March) is real and should not have to become a permanent scheme to be
recorded.

- Unique on `(school_id, code)`, like a fee head. Two campuses run their own schemes
  at their own rates.
- `code` is not editable, for the same reason a head's is not: it is the handle the
  school's own paperwork refers to.
- Deleting is **refused** while any student is on it, and the refusal names the
  count. Cascading would silently restore those families to full fees and nobody
  would find out until the challans printed. Deactivating is the retirement path.
- A remission is **clamped to the line it applies to**. A flat concession larger than
  the charge bills zero, not a negative — `ck_fee_voucher_items_amounts_valid` refuses
  a negative line, so without the clamp a generous scholarship becomes a failed
  billing run for the whole class.
- `fee:manage`. It answers what may go on a challan and at what number, which is the
  question fee heads answer.

**On the printed challan the gross survives beside the remission.** Lines print
gross, then `Subtotal`, then `Less concession`, then `Total payable`. Two reasons,
and the second is the one that matters:

1. **The column must add up.** Printing net lines *and* a discount row subtracts the
   remission twice on paper: a parent totalling the column gets a smaller figure than
   the total and brings the challan to the counter.
2. A remission the family cannot see is one they were not told about. Quietly
   lowering the line is indistinguishable from a repricing, and the scholarship stops
   being something the school gets credit for.

### 5.3 Voucher (challan) — `fee_vouchers` + `fee_voucher_items`

One student's bill for one period.

```
DRAFT ──issue──> ISSUED ──payment──> PARTLY_PAID ──payment──> PAID
  │                 │                      │
  │                 └──due date passes──> OVERDUE ──payment──> PARTLY_PAID / PAID
  │                 │                      │
  └───void──────────┴──────void────────────┘        (PAID cannot be voided)
```

- `voucher_number` is unique per school, format `FV-<year>-<5 digits>`.
- **Amounts are snapshotted at generation.** Each `fee_voucher_item` copies both the
  amount *and* the head's name. Renaming "Tuition" to "Tuition & Lab" next term must
  not silently reword a challan a parent already holds, and a structure price change
  must not restate what was billed in August. This is the same rule the billing
  module applies to invoices: issued money records are immutable, corrections are
  new records.
- Unique on `(school_id, student_id, academic_year, period_label)` **where status is
  not `void`**. A partial unique index, so a student cannot be billed twice for
  August 2026, while a voided challan can be reissued for the same period.
- `OVERDUE` is derived, not stored as a separate write path: a voucher with
  `due_date < today` and an outstanding balance reads as `OVERDUE`. Slice 1 computes
  it on read; a maintenance job that materialises it is additive.
- Voiding requires `fee:void` and is refused when any non-reversed payment exists —
  reverse the payments first. `void_reason` is mandatory and lands in the audit row.
- **No soft delete.** `fee_vouchers` carries no `deleted_at`. A financial record is
  voided, never deleted, and omitting the column makes that contract visible in the
  schema rather than relying on everyone remembering it.

### 5.4 Payment — `fee_payments`

Money received against one voucher.

```
RECORDED ──reverse──> REVERSED
```

- `receipt_number` is unique per school, format `RC-<year>-<5 digits>`.
- `method` is `cash` | `bank_transfer` | `cheque` | `card` | `online` | `other`.
  `reference` holds the cheque number or bank transaction id.
- Amount must be `> 0` and must not exceed the voucher's outstanding balance.
  Overpayment is rejected rather than parked as credit, because credit with no
  ledger to hold it is a number that goes missing.
- Payments cannot be recorded against a `DRAFT` or `VOID` voucher.
- Reversal requires `fee:void`, needs a reason, and recomputes the voucher. The
  payment row stays — a reversed receipt is part of the trail.
- `received_by_user_id` records who took the money, separately from
  `audit_logs.actor_user_id`, because cash handed to one clerk is sometimes entered
  by another and the school needs both names.

### 5.5 Stationery on a challan — the two ways it gets there

**Per class, through the structure.** "Every child in Grade 1 gets twelve copies and
the book set" is a property of the class. Generation copies those lines onto every
voucher it creates, snapshotting the name, the unit, the quantity and the price.

`POST /fees/vouchers/generate` takes `include_stationery` (default `true`) for
exactly one reason: a structure holding an **annual** book set would otherwise
re-bill those books on every monthly run — twelve times the books, at the parent's
expense. The monthly runs turn it off; the August run leaves it on.

**Per student, on a draft.** "Ali also took two more copies in October" is not a
class fact. `PUT /fees/vouchers/{id}/stationery` charges one article to one
student's challan, and is idempotent by article — sending the same item twice sets
the quantity rather than adding a second "Copy" line beneath the first. An optional
`unit_price` overrides the catalog for that one line, for the real case of a damaged
or part-used article sold cheap.

**Both paths are DRAFT-only, and that is the immutability rule, not a limitation.**
A parent holding a challan for 6,500 must not discover at the counter that a clerk
made it 6,800 this morning; a school that can restate an issued bill has no defence
when a parent says the amount changed after they were handed it. So the flow is:
generate the period's challans as drafts, walk the class adding what each student
actually took, then issue. That is the order a school office already works in. For a
student who takes something *after* their challan went out, the charge belongs on
next period's challan — which is also how the school's own ledger treats it.

`fee_voucher_items` gained `updated_at` for this: the rows are no longer written
exactly once. The rule was never "a line is never written twice" — it was "a bill in
a parent's hands is never rewritten", and a draft is in nobody's hands.

**On the printed challan** a stationery line shows its working:
`Copy (Register, 100 pages) — 3 pieces @ 60.00`. A parent handed a line reading only
"Copy — 180" cannot check it and the counter clerk cannot answer them; printing the
count and the unit price turns a disputed line into arithmetic anyone can redo.
Stationery lines sort below every fee line, because a parent reads the tuition line
first and a challan that interleaves books between tuition and transport generates
phone calls.

### 5.5b One-off charges — a fine, a re-exam fee, a broken window

`PUT /fees/vouchers/{id}/charges` puts one fee head on **one** student's draft
challan at an amount typed now. It is the fee-side twin of the stationery path and is
deliberately shaped identically: draft-only, idempotent by head, re-snapshotting the
head's name while the bill is still being assembled.

**Why it needed a route rather than a workaround.** Without it, the only tool an
operator has for *"charge Ali 500 for the lab window"* is the **class structure** —
add a Breakage line, generate, remove it next month. That bills the whole grade for
one broken window, and forty parents find the error before the school does.

- Charging a head the structure already priced **restates** that line rather than
  adding a second one. Correct on a bill still being assembled — the last word wins —
  and the audit row carries the figure that was there before.
- The matching `DELETE` will remove a line the class structure put there, which is
  the supported way to say *"this student is not paying the exam fee this term"*
  without touching the structure every other student is billed from. The standing
  version of the same intent is an `excluded` assignment.
- `fee:issue`. It decides who is charged, not what may be charged.

### 5.6 Late fee policy — `fee_late_fee_policies`

One rule per school per academic year, enforced by a **partial unique index** on
`(school_id, academic_year) WHERE is_active AND deleted_at IS NULL`. Two live
policies would make the fine a family owes depend on which row the job read first.

Fields: the `head_id` fines are billed under, `kind` (`fixed` | `percent` of the
**outstanding** balance), `value`, `grace_days`, `recurrence` (`once` | `weekly` |
`monthly`), `max_amount`, `min_outstanding`.

**A policy, because the alternative is fining the families somebody remembered.**
Fines applied by hand are applied unevenly, and unevenly always means the same thing
in practice: the families who complain are let off and the ones who do not are
charged. That is a process failure rather than a moral one — nobody applies a rule
consistently across four hundred challans by hand every month. So the rule is a row,
the job applies it to everyone it matches, and the exceptions are visible: letting a
family off is **voiding a challan**, with a reason, audited.

**The fine is a new challan, not an extra line on the late one.** Rule 1 says an
issued bill is never rewritten, and a fine assessed three weeks after issue would
rewrite one. So the run mints a voucher with `origin = late_fee` and
`source_voucher_id` pointing back at the challan it punishes — payable, printable and
voidable through the machinery staff already use.

Four guards, because it runs unattended and **will** be re-run:

- `fines_for_source` counts what a challan already earned, so `once` never fires
  twice and a recurring rule only fires when a further interval has actually elapsed.
  Assessments are counted from elapsed intervals rather than a "last assessed"
  timestamp, which would drift with the hour the job happened to run.
- `max_amount` caps the **total** fined against one challan, measured against what
  was already charged. **Required** on any recurring policy: an uncapped one keeps
  charging a family who has already stopped being able to pay, which converts a
  collection tool into the reason a child leaves.
- `uq_fee_vouchers_student_period` refuses a duplicate at the storage layer even if
  the first two were both somehow wrong, so the worst case is a 409 rather than a
  family fined twice.
- The candidate set excludes `origin = late_fee`, so **a fine is never itself
  fined**. Without it the policy compounds and a 200-rupee penalty reaches four
  figures unattended.

Drafts, voided and fully-paid challans are never candidates. Paid is tested as
`total > paid_total` rather than against the stored status, because `OVERDUE` is
derived on read here and a challan settled this morning still carries yesterday's
status.

Runs on `make run-maintenance`, per school, for every year that has an active policy
— so the job is self-configuring and a school with no policy is skipped without a row
being read. `POST /fees/late-fee-policies/run` is the same operation on demand;
because it is idempotent, exposing it is safe.

### 5.6b Billing schedule — `fee_billing_schedules`

One schedule per school per academic year, enforced by a **partial unique index** on
`(school_id, academic_year) WHERE is_active AND deleted_at IS NULL`. Two live
schedules would make the day a family is billed depend on which row the job read
first.

Fields: `generate_day` (1–28), `due_day_offset`, `issue_immediately`,
`include_stationery`, `carry_forward_dues` + `carry_forward_head_id`, and a receipt
of the last run (`last_run_period`, `last_run_at`, `last_run_created`,
`last_run_skipped`).

**The cron is dumb on purpose.** The scheduler outside the process knows one thing:
run daily. Everything that varies per school is this row, so the owner can read it
and change it. A crontab per tenant puts the school's own billing day in a file the
school cannot see, cannot change without an engineer, and which silently disagrees
with what the settings screen claims.

**Capped at day 28, not clamped from 31.** A school that picks the 31st means "the
end of the month", but February would move that to the 28th while the family's
standing bank instruction did not move with it. Refusing 29–31 at the boundary makes
the question get answered once, by the owner.

**Both dangerous switches default off.** `issue_immediately` hands out real bills
unattended — they count towards outstanding, earn late fees, and are undone by
voiding with a reason. `include_stationery` re-bills the book set every month, twelve
times a year. The manual dialog defaults `include_stationery` **on**, because that
run is usually the admission-month one; a schedule fires twelve times, so it inherits
the opposite default.

**Safe to run twice, by two independent mechanisms.** `last_run_period` stops a
second pass doing work; `uq_fee_vouchers_student_period` stops a second pass
*billing* anyone it already billed even if the first crashed before writing its
bookmark. The second is the one that matters — a half-finished run is completed by
running it again, not by working out which students got a challan.

Runs on `make maintenance`, per school, before the late-fee pass — a challan
generated today is not yet due, so it cannot be fined by the run that follows it.
`POST /fees/billing-schedule/run` is the same operation on demand (`fee:issue`); it
skips the is-it-the-day test but **not** the has-this-period-been-generated one.

### 5.6c Carrying dues forward — `superseded_by_voucher_id`

By default a new challan **prints** the family's balance beside its total and bills
only its own period (§5.3). Consolidation is the other answer: the new challan bills
the unpaid earlier challans as a real line **and cancels them**, so exactly one
document is payable.

Both are correct, for different schools. A bank that reconciles per challan number
needs the first; parents paying one figure at one counter need the second. It is a
per-run flag (`carry_forward_dues`) and a schedule setting, never a global mode.

**A reservation first, a cancellation only at issue.** Generation stamps the older
challans with `superseded_by_voucher_id` and leaves them live. If the cancellation
happened there, a consolidating *draft* would take four real challans off the
family's balance while the only document covering that money sat unissued — the
school would read "nothing owed" about a family owing three months. The void and the
new charge happen together, at issue, so the balance never passes through a wrong
value.

**A part-paid challan is never absorbed.** Voiding a bill money was received against
would orphan the receipt, which `void_voucher` refuses outright. Its remaining
balance keeps its own document and prints beside the new total as before.

**A reserved challan that takes a payment before the new one is issued is released,
and the arrears line shrinks to match.** That repricing is legal only because the
consolidating voucher is still a draft at that moment — it is the last point the
correction can be made, which is why it is made there. Voiding a consolidating draft
also releases everything it reserved, so nothing is stranded outside future runs.

The pointer doubles as a lock: a challan already carrying it is not offered to the
next run, so two consolidations cannot each bill the same arrears.

### 5.7 Student ledger — `student_ledger_entries`

Append-only, one row per money movement, with the running `balance_after`
denormalised onto each. Entry types: `charge`, `payment`, `payment_reversed`,
`voucher_voided`, `late_fee`, `adjustment`.

**Why materialise a number that can be computed.** *"What does this family owe?"* was
answerable in slice 1 by summing unpaid vouchers, and that answer is correct. It is
also recomputed per request, cannot be indexed, and cannot answer the question a
parent actually asks at the counter — *"how did it get to that number?"* This table
answers both: the balance is one row read, and the movements that produced it are the
rows above it, each pointing at the voucher or receipt that justifies it. That is a
**statement**, which an aggregate query can never produce.

- `CreatedAtMixin` and no `deleted_at`: there is no path that updates or removes a
  row. A correction is a **new** entry. The missing columns are the contract.
- `amount` is **signed** — positive debits, negative credits. One column rather than
  two, because every consumer wants the net and a two-column ledger makes every one
  of them write the same CASE expression, and get it wrong once.
- Entries are appended under a **lock on the student row**. Two concurrent appends
  reading the same previous balance would both write the same next one, and the
  statement would show two movements and one of their effects. A cashier taking a
  payment while the late-fee job runs is an ordinary Tuesday.
- A **draft produces no entry.** A draft is not a bill, and a ledger that counted
  drafts would show families owing money nobody has asked them for. Voiding a draft
  therefore credits nothing.
- `balance` may be **negative** — the family paid in advance, or a payment was
  reversed after a refund. It is not clamped to zero, because clamping loses money
  the school is actually holding.
- A manual `adjustment` requires **`fee:void`**, not `fee:collect`. It is the one
  action in the module that moves money with no voucher and no receipt behind it,
  which makes it the one an accountant could use to cover a shortfall.

**The ledger is a record, not the source of truth.** `fee_vouchers` and `fee_payments`
remain authoritative. `make reconcile-ledger` recomputes from them and **reports**
disagreement rather than repairing it — a balance that silently corrects itself every
night is indistinguishable from one that was right all along, and the cause of the
drift is the thing worth finding. A manual adjustment is the expected legitimate
difference, so a non-empty report is a prompt to read the statements, not an alarm.

**Arrears are carried forward by printing, unless the run consolidates.** By default
each generated challan snapshots the family's balance into `arrears_brought_forward`
and prints it as *"Previous balance (billed separately)"* with a *"Total including
previous balance"* line beneath, deliberately **absent from `total`**: the older
challan carrying that balance is still outstanding and still payable on its own, so
adding it here would bill the same rupee twice — and the school would find out at the
counter, with the parent holding both pieces of paper.

A run with `carry_forward_dues` makes that sentence false instead of ignoring it: the
absorbed challans are billed as a real line **and cancelled**, so exactly one document
is payable and `arrears_brought_forward` keeps only what could not be absorbed. See
§5.6c for why the cancellation waits until the new challan is issued.

## 6. Required fields and uniqueness — summary

| Table | Not-null business fields | Unique |
| --- | --- | --- |
| `fee_heads` | `code`, `name`, `recurrence`, `is_active` | `(school_id, code)` |
| `fee_structures` | `class_id`, `academic_year`, `name`, `status` | `(school_id, class_id, academic_year)` |
| `stationery_items` | `code`, `name`, `category`, `unit`, `unit_price ≥ 0`, `is_active` | `(school_id, code)` |
| `fee_structure_items` | `structure_id`, `line_type`, `quantity > 0`, `unit_price ≥ 0`, `amount ≥ 0` | `(structure_id, head_id)` where not null; `(structure_id, stationery_item_id)` where not null |
| `student_fee_assignments` | `student_id`, `head_id`, `academic_year`, `mode` | `(student_id, academic_year, head_id)` |
| `fee_vouchers` | `student_id`, `voucher_number`, `academic_year`, `period_label`, `issue_date`, `due_date`, `status`, `currency`, totals | `(school_id, voucher_number)`; `(school_id, student_id, academic_year, period_label)` where not void |
| `fee_voucher_items` | `voucher_id`, `line_type`, `line_name`, `quantity > 0`, `unit_price ≥ 0`, `amount ≥ 0`, `discount_amount ≥ 0` | `(voucher_id, head_id)` where not null; `(voucher_id, stationery_item_id)` where not null |
| `fee_payments` | `voucher_id`, `receipt_number`, `amount > 0`, `currency`, `method`, `received_on`, `status` | `(school_id, receipt_number)` |

Both item tables additionally carry a `line_type_matches_reference` CHECK: exactly
one of `head_id` / `stationery_item_id` is set, and it is the one `line_type` claims.
`head_id` became nullable when stationery landed; that CHECK is what keeps it
required on every line where it ever meant anything.

Every table carries non-null `organization_id` (RLS key) and non-null `school_id`
(scope filter). There is no org-level fee record — fees are always a campus concern.

## 7. School-year behaviour

`academic_year` is a validated string, `NNNN-NNNN` with consecutive years
(`2026-2027`), stored on structures and copied onto vouchers.

**Why a string and not an `academic_sessions` table.** An academic session is an
academics concept — terms, holidays, promotion, result cards all key off it — and
inventing it inside the fees module would put the calendar that governs the whole
school under Finance's ownership. Fees needs exactly one thing from it: a stable
label to group a year's billing under. When academics introduces the real entity,
the migration is mechanical: add a nullable `academic_session_id`, backfill by
matching the label, then drop the string. Nothing in this module's behaviour changes.

`period_label` is free text up to 40 characters (`2026-08`, `Term 1`, `Annual`)
because monthly, termly and annual schools all exist and a fixed enum would exclude
one of them.

## 8. Bulk operations

`POST /fees/vouchers/generate` is the only bulk write. `POST
/fees/billing-schedule/run` and the nightly job call it once per active structure
(§5.6b) rather than duplicating any of it.

- Input: an `ACTIVE` structure, a `period_label`, `issue_date`, `due_date`, an
  optional `section_id` filter, an optional explicit `student_ids` list,
  `issue_immediately`, `include_stationery` (§5.5), and `carry_forward_dues` +
  `carry_forward_head_id` (§5.6c).
- Targets every `ACTIVE`, non-deleted student in the structure's class (narrowed by
  the filters), at the caller's school.
- **Skips rather than fails.** A student who already has a non-void voucher for that
  `(academic_year, period_label)` is skipped with a reason, and the rest still
  generate. A partial failure that rolls back 400 challans because one student was
  already billed is not a usable product.
- Response is a receipt of the run: `created`, `skipped[]` with `{student_id,
  admission_number, reason}`, and the created voucher ids.
- Runs in one transaction with one audit row for the batch plus one per voucher.
- Capped at 500 students per call; beyond that the caller filters by section. The cap
  is explicit in the response so a truncated run can never read as a complete one.
- A consolidating run additionally reports `absorbed_vouchers` and `absorbed_total`.
  Those challans are RESERVED at generation and cancelled only when the new one is
  issued, so a run that produced drafts has reserved that many and cancelled none.

## 9. Reports and exports

- `GET /fees/summary` — billed, collected, outstanding, `stationery_billed`, and
  voucher counts by status for an `academic_year` and optional `period_label`. Three
  queries regardless of school size, never N+1. `stationery_billed` is a **part** of
  `billed`, summed from the challan lines over the same row set (void and draft
  excluded) — computing a component over a different row set than its whole is how a
  dashboard ends up showing a part larger than the total it belongs to.
- `GET /fees/vouchers/{id}/pdf` — the printable challan: one A4 page carrying the
  campus's detachable copies (Bank / School / Student by default), each a ruled grid
  in the shape a Pakistani bank counter reads — a letterhead with the school's name,
  address and phone between two copies of its logo (the campus logo, else the
  organization's; only uploaded logos print, an `https://` link is never fetched),
  the accounts to credit across the head, then the student's identifiers and challan numbers, name, father, contact,
  class and section, the due date, then `Fee Month | Particular | Payable` lines
  (stationery with its quantity and unit price), the total, the total in words, the
  two payable lines, and a blank for the counter's stamp and signature. See §9.1.
- `GET /fees/vouchers/print?ids=…` — the same page covering **several** vouchers for
  one student: a term billed at once prints as Jul / Aug / Sep rows under one total
  and one challan-number band. The vouchers stay separate underneath, so paying two
  of three settles exactly those two; this combines the printing, not the billing.
  Capped at 12 ids. Refuses, with a 404 or a 422, anything that would misbill: an id
  that does not resolve (never a silently shorter challan), two students on one page
  (`CHALLAN_MIXED_STUDENTS`), or a voided charge folded into a live total
  (`CHALLAN_VOID_COMBINED`). A voided challan still reprints **on its own**, with a
  VOID band across it — that is how an office shows a bill was cancelled.

### 9.1 The printed challan

**It is a bank document before it is a school document.** A parent carries it to a
counter where a clerk reads four things in a fixed order — the account to credit, who
the payer is, the amount, and the date after which the amount changes — in the shape
every other challan in the country uses. That is why the layout is a ruled grid in a
plain sans face (Helvetica — a base-14 font, so it needs no embedding and cannot
fail to resolve in whatever reader the bank has), black on white, with one grey
fill. A prettier page is one the clerk has to hunt through, and hunting at a counter
with a queue behind it is how a payment gets credited to the wrong student.

| Element | Where it comes from | Why it is there |
| --- | --- | --- |
| Copies | `schools.challan_design.copies`, default all three | The bank keeps one, stamps and returns one, and the parent keeps one. A single-copy challan is refused at the counter. |
| Account band | `schools.challan_design.payment_accounts` (up to 4) | Where the family's money actually goes. It changes, and a stale number does not fail visibly — the transfer succeeds into an account the school cannot reconcile. It is therefore a campus row the office edits, never a constant. |
| Roll number | `student_enrollments.roll_number` for **the challan's own** academic year | Roll numbers are reissued every session. A reprint after promotion carrying this year's number against last year's fees cannot be matched to the register the office checks it against. |
| Fee Month | `fee_vouchers.period_label`, reformatted when it parses as `YYYY-MM` | The automated run writes "2026-08"; a parent reads "Aug, 2026". An office's own wording ("Term 1") is printed verbatim rather than corrected. |
| Particular | The **snapshotted** line name, gross | Gross lines plus one concession row, never net lines *and* a discount row — the column has to add up to the figure the parent is asked to pay, and it is the only way a family sees a remission they were granted. |
| Total in words | `app.common.money.amount_in_words`, South Asian scale | A figure in numerals can be altered with one pen stroke; 1,700 becomes 4,700 by closing the top of a 1. The clerk reconciles the two. Lakh and crore because that is what is said aloud at the counter. |
| Payable Within Due Date | Outstanding, not the total | On a reprint of a part-paid challan the figure to collect is what is **left**. A page repeating the original total is how a family pays twice. |
| Payable After Due Date | Outstanding + the active `fee_late_fee_policies` first assessment | A preview of the rule, not a ledger figure — `apply_late_fees` is what actually fines. No policy prints the same figure twice, which is the truth: this school does not charge for paying late. |
| Previous balance | `fee_vouchers.arrears_brought_forward`, labelled *billed separately* | Unchanged from §5.7: printed, never folded into the total, because the older challan carrying it is still payable on its own. |
| Printed By | The caller's `users.full_name` | A challan is money changing hands. "Who printed this one?", asked six weeks later, needs an answer on the paper rather than only in a log the counter staff cannot read. |

**The page measures itself.** A challan's height is not knowable in advance — it
depends on how many months print together, how many stationery lines a family took,
how many accounts the school names. So the type size starts at the comfortable size
for the copy count and shrinks only while the page says it does not fit, down to a
floor below which a clerk starts guessing at digits. Past the floor the honest
outcome is a second sheet, split between copies and never through one.

- `GET /fees/students/{id}/ledger` — the family's running account: the balance, and
  the movements that produced it, newest first (§5.7).
- `GET /fees/vouchers/export` — the voucher register as CSV, filterable by year,
  period and status. The register a finance office reconciles against its bank
  statement.

  **Capped at 5,000 rows, and the cap is announced inside the file.** This is the one
  read in the module a user can aim at every row the school has ever produced.
  Announcing truncation in a trailing comment rather than only in a response header
  is deliberate: the failure it guards against is someone opening the spreadsheet a
  week later, seeing 5,000 tidy rows, and reconciling against a year that had 7,000. A
  truncated export that reads as a complete one is worse than a refused one.

  Written with the `csv` module rather than string joins, because a student named
  O'Brien or a note containing a comma breaks naive quoting — and breaks it silently,
  shifting every subsequent column by one. The exported status comes through
  `_voucher_read`, so it matches the screen beside it rather than the stored value
  (`OVERDUE` is derived on read here).

## 10. Notification side effects

**None in slice 1.** No email, no SMS, no WhatsApp. Generating 400 challans must not
generate 400 messages to guardians before a human has checked the run, and the
absence of a review step in this slice is exactly why the notification is not wired
yet. `guardian_phone` on the student row is where the future reminder job reads
from.

## 11. Plan limits

Fees consume no plan capacity. Plans meter schools, staff and students; a school on
the free plan that bills its three students is not costing us more than one that
does not. No `entitlements.py` change, no 402 path in this module.

The suspension rule from the foundation still applies and is worth stating: a
suspended organization keeps **read** access to fee records. Withholding a school's
own financial records over a payment dispute with us is leverage we do not take.

## 12. Audit events

Every mutation writes an `audit_logs` row in the same transaction as the change.

| Action | `entity_type` | Notable payload |
| --- | --- | --- |
| `fee_head.created` / `.updated` / `.deleted` | `fee_head` | before/after |
| `fee_structure.created` / `.updated` / `.activated` / `.archived` | `fee_structure` | status transition |
| `fee_structure.item_changed` | `fee_structure` | head or article, old and new amount/quantity |
| `stationery_item.created` / `.updated` / `.deleted` | `stationery_item` | before/after, including both sides of a reprice |
| `fee_voucher.charge_added` / `.charge_removed` | `fee_voucher` | article, quantity, amount, whether the price was overridden |
| `student_fee.assigned` / `.unassigned` | `student` | head, mode, both sides of a rate change, note. `entity_type` is `student` rather than the join table: the question this answers is "what changed about what THIS CHILD pays", which an audit keyed on a join-table id cannot answer |
| `fee_voucher.generated` | `fee_structure` | batch: counts, period, filters, and — when the run consolidated — how many older challans it absorbed and for how much |
| `fee_voucher.issued` | `fee_voucher` | voucher number, total |
| `fee_voucher.voided` | `fee_voucher` | reason, total forgone |
| `fee_payment.recorded` | `fee_payment` | receipt number, amount, method |
| `fee_payment.reversed` | `fee_payment` | reason, amount |
| `fee_concession.created` / `.updated` / `.deleted` | `fee_concession` | both sides of a rate change |
| `fee_billing_schedule.set` | `fee_billing_schedule` | day, due offset, and both dangerous switches — drafts-or-issued and carry-forward |
| `fee_billing_run.completed` | `fee_billing_schedule` | period, structures billed, created, skipped, whether it was forced from the screen. **`actor_user_id` is NULL** on the nightly pass, for the same reason the late-fee run's is: *"who billed us?"* is answered by *"the schedule did"* |
| `fee_late_fee_policy.set` / `.deleted` | `fee_late_fee_policy` | kind, value, grace, recurrence, cap |
| `fee_late_fee.applied` | `fee_late_fee_policy` | run summary: considered, assessed, total charged, skipped, truncated. **`actor_user_id` is NULL** when the scheduled job wrote it — the only such action in this module, and honest: *"who fined us?"* is answered by *"the policy did"*, not by a system user that does not exist |
| `fee_ledger.adjusted` | `student` | signed amount, resulting balance, required description |

## 13. Retention, export, soft delete and restoration

| Entity | Delete behaviour | Retention |
| --- | --- | --- |
| `fee_heads`, `stationery_items`, `fee_structures`, `student_fee_assignments` | Soft delete (`deleted_at`); restorable by clearing it | Follows the organization's audit retention |
| `fee_structure_items` | Hard delete — configuration, not a financial record; every voucher took its own snapshot | — |
| `fee_vouchers`, `fee_voucher_items` | **No delete.** Void only | Kept for the life of the organization |
| `fee_payments` | **No delete.** Reverse only | Kept for the life of the organization |

Financial records are retained through the 30-day post-cancellation anonymization
job: the job scrubs personal identifiers, not the money trail, because a school that
returns — or an auditor who asks — needs the amounts to still reconcile. Deleting an
organization outright still cascades everything via `organization_id`, which is the
GDPR erasure path and is unchanged.

## 14. Acceptance tests (release gate)

Slice 1 ships when all of these pass against real PostgreSQL, with the app connected
as the restricted `sms_app` role.

**Isolation** (the gate that matters most)

1. Org A cannot read Org B's fee heads, structures, vouchers or payments; known ids
   return 404, not 403.
2. Org A cannot mutate any Org B fee row; B's rows are byte-identical afterwards.
3. A School A accountant cannot read or mutate School B's vouchers inside the same
   organization; an org-level principal can read both.
4. Direct SQL as `sms_app` cannot insert a fee row stamped with another tenant's
   `organization_id`.

**Behaviour**

5. Generation creates one voucher per eligible student, snapshots amounts and head
   names, and skips already-billed students with a reason.
6. Renaming a fee head or repricing a structure item does not change any existing
   voucher.
7. A payment exceeding the outstanding balance is rejected; an exact payment moves
   the voucher to `PAID`; a partial one to `PARTLY_PAID`.
8. Payments are rejected against `DRAFT` and `VOID` vouchers.
9. Voiding is refused while a non-reversed payment exists, and succeeds after
   reversal.
10. Reversing a payment restores the voucher's outstanding balance and status.
11. A voucher cannot be created twice for the same student, year and period; after
    voiding, it can.
12. `fee:collect` alone cannot void; `fee:void` alone cannot record a payment.
13. Every mutation above has a matching `audit_logs` row in the same transaction.

**Unattended generation and consolidation** — `tests/integration/test_fees_automation.py`

14. A campus with no schedule reads as `null`, not 404; the schedule upserts by year
    and reports its own next run date.
15. Pausing keeps every setting and clears the next run; a schedule that carries dues
    forward without naming a head is refused at the boundary, not by the CHECK.
16. Running twice bills the period once. The second call answers *"already
    generated"* rather than failing, and two students produce two challans, not four.
17. The run records a receipt of itself — a run that created 0 and skipped 400 is
    distinguishable from one that never happened.
18. Configuring needs `fee:manage`; running needs `fee:issue`. Neither implies the
    other.
19. A consolidating run bills September's own 6,500 plus August's 6,500 as one 13,000
    challan, voids August with a reason naming its replacement, and leaves the
    family's balance at 13,000 — **not** 19,500.
20. A consolidating **draft** leaves the absorbed challan live and payable; the
    cancellation and the new charge happen together, at issue.
21. A part-paid challan is never absorbed; its remaining balance prints beside the
    new total as before.
22. Paying a reserved challan before the new one is issued releases it and removes
    the arrears line — the reserved challan ends `PAID`, never voided.
23. Voiding a consolidating draft releases everything it reserved, and the next run
    is offered those challans rather than finding them stranded.
14. The challan PDF renders one A4 page with three copies and the correct totals,
    each carrying the template's bands (`Fee Month` / `Particular` / `Payable`, the
    total, the total in words, the two payable lines, the signature block).
14a. The campus's `challan_design` decides which copies print and which accounts
    appear; a campus that never opened the designer prints the standard challan.
14b. Several vouchers for one student print as one challan, with every challan
    number in the band and every period as its own row. An unresolvable id 404s, two
    students 422, and a voided challan cannot join a live total — but still reprints
    alone, marked VOID.

**Stationery**

15. A stationery line bills `quantity × unit_price`, and the structure line, the
    challan line and the voucher total all agree.
16. `include_stationery=false` bills the fees alone, so a monthly run of a structure
    carrying an annual book set does not re-charge the books.
17. A charge can be added to, adjusted on and removed from a DRAFT challan; the
    voucher total is recomputed from the lines each time. Both are refused with 409
    once the challan is issued, and the issued total is untouched.
18. Repricing or renaming a catalog article changes neither an issued challan nor
    the structure line that froze its price; re-adding the line picks the new price
    up for the next run.
19. An article charged on any line cannot be deleted; deactivating it retires it
    without breaking the challans that sold it, and it cannot be charged again.
20. `stationery_billed` is a part of `billed` over the same row set — voiding a
    challan removes it from both.
21. Every catalog change and every ad-hoc charge writes an audit row, with both
    sides of a reprice.
22. `fee:manage` owns the catalog and cannot charge a student; `fee:issue` charges a
    student and cannot touch the catalog.

**Per-student arrangements**

23. A student with no assignments is billed their class base exactly.
24. Adding a head bills that student and no classmate; excluding one leaves the line
    off their challan entirely rather than zeroing it.
25. Generation bills each student their own effective lines, and every challan agrees
    with the profile preview that produced it.
26. Changing a rate updates the existing arrangement rather than creating a second
    one, and never restates an issued challan — it applies from the next run.
27. Removing an arrangement returns the student to their class default.
28. An `added` row without an amount and an `excluded` row with one are both refused
    with 422, naming the field.
29. A head assigned to any student cannot be deleted, and the refusal says so.
30. A student in no section, or whose class has no structure for the year, gets an
    empty profile rather than a 404.
31. Assigning requires `fee:manage`; `fee:issue` alone can read the profile and not
    change it.
32. Every assignment change writes an audit row against the STUDENT, carrying both
    sides of a rate change.

**Concessions, overrides and one-off charges (slice 2)**

33. A percentage concession reduces the line and the challan carries **both** numbers
    — gross on the line, remission in `discount_total`, net in `total`. A classmate
    with no arrangement is untouched.
34. The profile preview and the generated challan agree to the rupee on `gross_total`,
    `discount_total` and the net.
35. **A discount applies to an overridden rate, not to the class list price.** This is
    the order test, and the one that costs money if it regresses.
36. An `override` for a head the class does not price contributes nothing; it never
    becomes an added line.
37. A remission larger than the line bills zero, not a negative.
38. A `discount` with no rate, with two rates, an `override` with no amount, and a
    `percent` on an addition are each refused with 422.
39. Revising a scheme moves every student on it from the next run and restates no
    issued challan.
40. A scheme students are on cannot be deleted, and the refusal names the count;
    taking the last child off releases it.
41. A one-off charge hits one student's draft and no classmate; charging the same head
    twice sets the line rather than adding a second; it is refused with 409 once the
    challan is issued.

**Late fees (slice 2)**

42. A run with no active policy fines nobody and considers nothing.
43. An overdue challan produces a fine as its **own** voucher, `origin = late_fee`,
    linked by `source_voucher_id`, and the challan it punishes is byte-for-byte
    unchanged.
44. Re-running the same day assesses nothing further.
45. A fine is never itself a candidate — the policy cannot compound.
46. Grace days and `min_outstanding` each hold the run back, and the reason is
    reported per skipped challan.
47. A percentage fine is charged on the **outstanding** balance, not the original
    total.
48. A settled challan is never fined.
49. A recurring policy without a cap is refused with 422; a capped one stops at its
    cap and reports `cap_reached`.

**The student ledger (slice 2)**

50. Issuing writes a `charge`; a **draft writes nothing**, and voiding a draft credits
    nothing.
51. A payment credits, a reversal re-debits as a **new** entry, and voiding an issued
    challan credits it back.
52. `balance_after` tracks the running balance and the statement reads newest first.
53. **Arrears are printed and never billed**: the next period's challan carries
    `arrears_brought_forward` and a `total` covering only its own period.
54. A manual adjustment is refused for `fee:collect` and allowed for `fee:void`.
55. One organization's ledger is invisible to another through the application's own
    NOBYPASSRLS connection, and `WITH CHECK` refuses a cross-tenant insert.
56. The voucher register exports as CSV with a header row, one row per challan, and no
    truncation notice below the cap.
