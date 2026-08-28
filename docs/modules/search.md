# Global search module specification

> One omnibar over every entity a member can already read, with a filter syntax for
> the people who live in it. Implemented in `backend/app/modules/search/` and
> `frontend/src/components/search/`.

---

## 1. What this module is, and what it is not

**It is** a fan-out reader. Given a query string it runs one bounded, ranked query
per entity kind the caller is permitted to see, and returns the results grouped and
ordered by what someone in that role usually wants.

**It is not** a search index. There is no Elasticsearch, no denormalised document
store, no ingestion pipeline and nothing to reindex after a write. Queries run
against the live tables through the same connection and the same Row-Level Security
as every other read, which means a student enrolled two seconds ago is findable and
a student soft-deleted two seconds ago is not — without a single line of cache
invalidation.

**It owns no tables.** Adding it did not add a model, and `db/registry.py` is
unchanged. The only schema change is `f3a5c7e9b1d3`, which adds trigram indexes to
three existing tables.

The trade is deliberate and has a limit: this design is correct while a tenant's
largest table is in the low hundreds of thousands of rows. Past that the honest move
is a materialised search table fed by triggers, or a real index — and the seam for
it is `SearchRepository`, which is the only thing that knows any SQL.

---

## 2. Deliberate exclusions

| Not built | Why |
|---|---|
| Server-side recent searches | A row per keystroke per user, and the list of names staff look up is personal data with no operational use. Recents live in `localStorage`, on the device of the person who typed them. |
| Search analytics / popularity ranking | Same objection, plus it makes ranking depend on data we would have to retain and explain. |
| Saved searches | The query string IS the saved search — it is shareable text. A stored-object CRUD can be added later without changing the parser. |
| Cross-tenant search | There is no such thing. RLS bounds every query to one organization, including for platform operators, who reach a tenant only through the audited impersonation flow. |
| Full-text (`tsvector`) ranking | Names, admission numbers and voucher numbers are identifiers, not prose. Stemming "Ali" is meaningless; trigram similarity is the right tool for the data. |

---

## 3. Actors

| Actor | What search means to them |
|---|---|
| Principal (org-level) | Everything, across every campus. The only role that can widen scope with `school:all`. |
| Teacher | Their students and the sections they sit in. No money, no access configuration. |
| Accountant | Vouchers first; students as the route to a voucher. |
| Custom role | Exactly the intersection its permissions allow, ordered by what those permissions say the role *does*. No code change per role. |

---

## 4. Permissions

Search introduces **no new permission code**, and this is the central design
decision. A `search:read` code would grant nothing on its own and would 403 every
custom role that existed before it shipped.

Instead, authorisation is **per result, not per route**. `GET /search` is reachable
by any authenticated member; each entity kind is gated on the same permission its
own module's list endpoint uses:

| Entity | Required | Frontend destination |
|---|---|---|
| `student` | `student:read` | `/students/{id}` |
| `member` | `member:read` | `/members` |
| `voucher` | `fee:read` | `/fees/{id}` |
| `class`, `section` | `class:read` | `/classes` |
| `school` | `school:read` | `/schools/{id}` |
| `invitation` | `invitation:read` | `/invitations` |
| `fee_head`, `fee_structure` | `fee:read` | `/fees/setup` |
| `role` | `role:read` | `/roles` |
| `audit` | `audit:read` | `/audit` |

Only three destinations are precise records; the other eight modules have list pages
with no filter UI and no `q` parameter, so their hits land on the list. The templates
deliberately carry no `?q=`/`?role=` — nothing reads those, and a URL implying a
filter that was never applied is worse than an honestly coarse link. **Follow-up:**
when those pages grow a filter, add the parameter to `ProviderDef.url_template` and
every caller gets a precise link at once.

A provider that fails its check is **never queried** — its SQL is not built and not
parameterised. So "no results" and "not for you" are indistinguishable from the
outside, and the box cannot be used to enumerate which modules a tenant has or which
permissions the caller lacks. A `type:` naming an unreachable kind returns the same
`Unknown or unavailable type` warning as a typo, for the same reason.

`audit` is permitted but **out of the default scan**: it matches nearly any term
(it stores action names and entity types) and would drown the omnibar. It runs only
when named with `type:audit`.

---

## 5. The query language

Parsed by `modules/search/query.py`. The grammar is small on purpose.

| Form | Meaning |
|---|---|
| `ahmed` | Term. Must appear somewhere in the row. |
| `"grade 10"` | Phrase. Matched as a unit, not as two terms. |
| `-transferred` | Exclusion. Drops the row even if it matches otherwise. |
| `status:pending` | Filter. Multiple values of one key are OR'd; different keys are AND'd. |
| `-status:paid` | Negated filter. |
| `class:"Grade 10"` | Quoted filter value. |

Recognised keys: `type`, `status`, `school`, `class`, `section`, `role`, `year`,
`after`, `before`. Which ones do anything varies by entity and is published per
scope by `GET /search/config`.

### 5.1 Nothing the user types is an error

This runs on every debounced keystroke, so "not finished typing" must never look
like "wrong". Every malformed input has a defined reading:

- an unknown key (`foo:bar`) is **searched as literal text** and reported in
  `warnings` — guardian email addresses contain colons, and a 400 there would be
  absurd
- an unclosed quote is a bare word (the closing quote a user has not typed *yet*
  is the normal state of a box being typed into)
- a bad date is dropped from the filter, with a warning; the rest of the query runs
- over-long input is truncated, not rejected
- an empty `q` is an empty result, not a 422 — the omnibar calls this as the user
  clears the box

### 5.2 A filter value from another module matches nothing, by design

`status:paid` is a voucher status. Evaluated against students in a fan-out it
returns **zero students**, rather than being skipped. Skipping it would dump the
whole student directory into a search that plainly meant vouchers. Negation inverts
the reading: `-status:paid` excludes no students, because no student was ever paid.

---

## 6. Matching and ranking

Every needle must appear in at least one of a provider's searchable columns — AND
across needles, OR across columns.

| Strength | Test | Score |
|---|---|---|
| exact | `lower(col) = term` | 100 |
| prefix | `col ILIKE 'term%'` | 55 |
| contains | `col ILIKE '%term%'` | 25 |
| fuzzy | `lower(col) % term` (pg_trgm) | 0–20 |

A row takes the **best column** per needle (`greatest`), summed over needles — not
the sum across columns, which would rank large families above the person actually
named in the query.

Fuzzy tops out *below* `contains`: a literal hit must always beat a typo-similar
one, or the box stops being trustworthy. Fuzzy is enabled only for needles of 4+
characters, because trigram similarity on `10` is noise.

The final score is `text_score × role_weight` — **multiplied**, not added, so a
strong literal match still wins across type preferences. An accountant searching a
student's exact name gets that student first, ahead of a fuzzily-matched voucher.

---

## 7. Role-aware ordering

Two people typing `10` mean different things. Permissions cannot order results —
both a teacher and an accountant may read students.

`providers.profile_for()` derives a weight map per caller:

1. a baseline weight per entity (people and students above configuration objects)
2. plus boosts from the **work** permissions the caller holds — `fee:collect`
   boosts vouchers, `attendance:mark` boosts students and sections,
   `role:assign_permissions` boosts roles. Read codes contribute nothing: nearly
   everyone can read students, so `student:read` says nothing about intent.
3. plus a small explicit nudge for the three seeded role codes

Deriving from permissions rather than role names is what makes a customer's
"Registrar" role sensibly ordered on day one, and what makes removing fee access
from a role change that role's search ordering in the same edit.

Step 3 exists because a principal holds *every* code, so every work signal fires and
a purely derived profile flattens into "everything is equally important" — no
ordering at all, for the role that most needs one.

---

## 8. Scope

Two boundaries, enforced in different places on purpose.

**Organization** — PostgreSQL RLS, on every table. Nothing in this module can
disable it, and no code here has to remember it.

**Campus** — this module's job, because RLS deliberately permits an org-level member
to span campuses. `SearchService.resolve_scope` decides it once and passes it to
every provider as a value; it is never read from a request parameter inside the SQL.

`school:all` is the only widening operator, and it widens nothing:

- from a **campus-scoped** member it is acknowledged with a warning and **ignored**.
  Their scope is their membership's school, full stop.
- from an **org-level** member it sets aside the `X-Active-School` view preference.
  Their membership already spans the organization, so this removes a filter, not a
  boundary.

Models with a nullable `school_id` (roles, memberships, invitations, audit rows)
match their campus **or** the organization-level rows, because an org-level role
genuinely does apply to the campus being viewed.

---

## 9. Performance

One query per provider, run **sequentially** — one `AsyncSession` is one connection,
and concurrent statements on it are an error, not a speedup. Bounded by:

- `MAX_PROVIDERS_PER_SEARCH` (10), set to exactly today's default-scan set so it
  does not bite for any current role
- `limit` per group (5 by default, 25 max)
- parser caps: 6 terms, 8 filter values, 200 characters

The total per group comes from `count(*) OVER ()` in the same query — ten queries
per search rather than twenty. Safe here, unlike in `BaseRepository.list`, because
these selects project explicit columns and never eager-load a collection.

### 9.1 The trigram indexes are coupled to the SQL

Migration `f3a5c7e9b1d3` indexes `lower(coalesce(<column>, ''))` on `students`,
`fee_vouchers` and `users` — the three tables whose row count grows with how long a
customer has been using the product. The other eight are configuration a school
edits by hand, where a sequential scan over tens of rows beats an index lookup.

PostgreSQL matches an expression index only against a **syntactically identical**
expression, which is why `repository._text` emits exactly that shape, including the
`''` as a SQL literal rather than a bind parameter. Change `_text` and the indexes
silently stop being used: the queries stay correct and quietly get slower.

`EXPLAIN` on a fuzzy search should show a Bitmap Heap Scan, not a Seq Scan.

---

## 10. Privacy

**The query string is never logged.** `ahmed raza` typed into a school's search box
is a child's name; a log line outlives the request and ships wherever logs ship.
Term counts, provider names, group counts and timings are logged instead — enough to
debug a slow or empty search, and nothing more.

No audit row is written for a search. Search is a read, and the reads it performs
are ones the caller could already have made through each module's list endpoint.

---

## 11. Frontend contract

`GET /search/config` is what makes the omnibar role-aware without shipping the
permission catalog to the browser. It returns, for the caller: the scopes they may
search (ordered by their role profile), which filters each scope accepts, example
queries chosen for them, and whether `school:all` does anything.

The component holds **no permission logic**. It renders what it is told, which means
a permission change in the roles screen reshapes the box on the next load, and the
frontend can never disagree with the server about who may see what.

Scope chips write `type:` into the same string the user is typing rather than living
in separate state — so a query built by clicking can be edited by typing, copied,
and pasted back.

---

## 12. Acceptance tests (release gate)

`backend/tests/integration/test_search.py`, run against the app's own `sms_app`
connection (`NOBYPASSRLS`), so the isolation cases exercise PostgreSQL's policies.

| # | Case |
|---|---|
| 1 | Two roles, one query → different sets of `searched_types`, not just different rows |
| 2 | `type:` naming a forbidden kind → no rows, and a warning that does not distinguish "unknown" from "not permitted" |
| 3 | `/search/config` returns a different, correctly-ordered scope list per role |
| 4 | `status:` filter and `-exclusion` narrow the result set |
| 5 | A status value from another module matches nothing here |
| 6 | An unknown filter is searched as text, with a warning, and never a 4xx |
| 7 | Empty / whitespace `q` → empty result, not an error |
| 8 | `muhamad` finds `Muhammad` |
| 9 | An exact match outranks a partial one |
| 10 | A hit carries its deep link, and `matched_on` names the visible field |
| 11 | A match on a hidden field reports `matched_on: null` |
| 12 | `/suggest` ranks identically to `/search` |
| 13 | A campus-scoped member cannot widen scope with `school:all` |
| 14 | An org-level member can, and results carry their campus name |
| 15 | Two tenants with identical student names never see each other's rows |
| 16 | The route requires a session |
