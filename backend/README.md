# EduCloud — Backend

Multi-tenant school management platform.
FastAPI · Pydantic v2 · SQLAlchemy 2.x (async) · Alembic · PostgreSQL · Redis.

This is the **foundation**: identity, tenancy, RBAC, plans, billing hooks and
invitations — `educloud-core-spec.md` phases 0–5, plus the platform super-admin
console. Academic modules (attendance, gradebook, fees, timetable) hang off
`organization_id`, `school_id` and the permission catalog defined here.

---

## The four decisions everything else follows from

Spec decisions D1–D4. They shape every table and endpoint, and reversing any of them
is expensive — so they are stated up front rather than left to be inferred.

**D1 — The tenant is the ORGANIZATION, not the school.**
A client account (`organizations`) owns many `schools`. One subscription per
organization; the plan caps how many schools it may create. The billing boundary and
the isolation boundary have to be the same thing, or "which of these three campuses
owns the invoice?" has no answer.

**D2 — Owner and Principal are different roles.**
*Owner* is org-level: billing, school creation, visibility across every school.
*Principal* is school-level: runs one campus, no billing rights, cannot create
schools. On signup the owner gets an org-level owner membership; on creating their
**first** school they additionally get a school-scoped principal membership on it.
Two memberships, two scopes, one human — which is what later lets them hand Principal
to an employee while keeping owner rights.

**D3 — Isolation is Postgres RLS keyed on `organization_id`; `school_id` is a scope
filter inside it.**
The hard boundary is enforced by the database. The soft boundary — which campus you
see inside your own organization — is enforced by the permission dependency. Two
different problems, two different mechanisms.

**D4 — Identity is global, membership is scoped.**
One `users` row per human, globally unique email. A person may be a teacher at School
A and an accountant at School B. The access token names **one** membership; switching
context re-issues it.

---

## Quick start

```bash
make install                                        # dependencies

psql -U postgres -d school_manage_db \
     -f scripts/init-db.sql                         # extensions + restricted role (once)

cp .env.example .env                                # set SECRET_KEY and POSTGRES_*

make migrate                                        # schema + RLS policies
make seed                                           # permissions, plans, super admin
make seed-demo                                      # optional: demo org, schools, invites

make dev                                            # http://localhost:8000/docs
make check                                          # lint + typecheck + tests
```

Or the whole stack in containers: `make docker-up` (PostgreSQL + Redis + API).

The application boots and serves `/health` with **no database**; set `DB_ENABLED=true`
once PostgreSQL is provisioned.

---

## The architecture in one picture

```
HTTP request
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ MIDDLEWARE      request id, access log, CORS, gzip          │
├─────────────────────────────────────────────────────────────┤
│ DEPENDENCY      api/deps.py — require("member:invite")      │
│                 decodes the token, publishes org + school   │
│                 into ContextVars, resolves permissions.     │
│                 THIS ORDERING IS WHAT ARMS RLS.             │
├─────────────────────────────────────────────────────────────┤
│ ROUTER          app/modules/<m>/router.py                   │
│                 HTTP only: parse, validate, delegate.       │
├─────────────────────────────────────────────────────────────┤
│ SERVICE         app/modules/<m>/service.py                  │
│                 Business rules, invariants, transaction     │
│                 boundaries. Knows nothing about HTTP.       │
├─────────────────────────────────────────────────────────────┤
│ REPOSITORY      app/modules/<m>/repository.py               │
│                 SQL only. Knows nothing about business.     │
├─────────────────────────────────────────────────────────────┤
│ MODEL           app/modules/<m>/models.py                   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
PostgreSQL — Row-Level Security enforces the tenant boundary
```

**The dependency rule:** arrows point *downward only*. A service may import a
repository; a repository may never import a service. A service may never import
`fastapi`. That is what keeps services usable from the CLI, a background worker, or a
test with no HTTP client — and it is why the seed command can build a demo
organization by calling the same code the API calls.

---

## How tenant isolation actually works

Three layers, in increasing order of trustworthiness. Only the second is a real
boundary.

**Layer 1 — the application.** Services filter by scope. Convenient, and *not* relied
upon: one forgotten filter would be a permanent leak.

**Layer 2 — the database. THE REAL BOUNDARY.** Every tenant table carries
`organization_id NOT NULL` and a forced policy:

```sql
USING      (organization_id = current_org OR is_platform_admin = 'on')
WITH CHECK (organization_id = current_org)              -- no admin escape
```

PostgreSQL appends that predicate to *every* statement — ORM queries, raw SQL,
`text()`. A developer cannot write a query returning another organization's rows.

The asymmetry is deliberate: a platform operator may **read** across tenants for
support and billing, but may not **write** into one. Writes on a tenant's behalf go
through endpoints that first bind that organization's own id, so they land in its
audit trail instead of materialising from nowhere.

**Layer 3 — the role.** The app connects as `sms_app`: `NOSUPERUSER`, `NOBYPASSRLS`,
owns nothing. Superusers and table owners bypass RLS *silently*, so an app connecting
as `postgres` would have every policy above quietly disabled. Alembic connects as the
owner; the app never does. This is the most commonly missed step in RLS deployments —
`test_isolation.py` fails loudly if it regresses.

**School scoping is not RLS.** `school_id` is enforced by the permission dependency,
which injects a filter for school-scoped memberships and omits it for org-level ones.
Crossing schools inside your own organization is a permissions question; crossing
organizations is a containment question, and only the latter warrants the database
refusing to cooperate.

---

## Authorization

One dependency, on every route:

```python
@router.post("/schools/{school_id}/invitations")
async def invite(
    payload: InvitationCreate,
    ctx: AuthContext = Depends(require("member:invite")),
): ...
```

There is no `if user.role == "principal"` anywhere, deliberately. A role-name check
cannot express the custom roles customers create, drifts as roles gain permissions,
and leaves "who can invite staff?" un-answerable without grepping.

**Permissions are not in the token.** Only `pv` — the role's `permissions_version` —
is. The set resolves per request from Redis, keyed `perm:{role_id}:{pv}`. Editing a
role increments `pv`, so every existing token resolves against a fresh key and picks
up the change on the affected member's **next request**. That is the fix for the
classic "I revoked their access fifteen minutes ago and they can still delete
records" bug.

With `REDIS_ENABLED=false` everything still works — resolution falls back to
Postgres. Correctness is unaffected; latency is not.

### The escalation guards (spec §5.3)

The part the spec calls "the part that gets built wrong". All four are server-side,
all four have tests naming the escalation they prevent:

1. **No self-elevation beyond own grant** — `granted ⊆ actor_permissions`. Applies to
   role edits *and* invitations, or invitation becomes an escalation backdoor.
2. **No editing locked roles** — `owner` and `principal` are `is_editable = false`.
   Guard 1 alone does not cover this: editing your own role only grants what you
   already hold, so the subset check passes.
3. **No scope crossing** — a school-scoped actor touches only its own school's roles,
   and no school role may hold an org-scoped permission (422, not 403 — the request
   is incoherent rather than forbidden).
4. **The last owner is immovable** — an organization with no owner has nobody who can
   pay for it or appoint a replacement, and there is no in-app recovery.

---

## Layout

```
app/
  core/          config, context (ContextVars), security (JWT + opaque tokens),
                 passwords (zxcvbn policy), cache (permission cache), logging
  db/            Base, mixins (TenantMixin -> organization_id), session (RLS GUCs)
  api/           deps.py (require(), AuthContext), cookies.py, errors.py, v1/router.py
  common/        audit, email, repository, schemas
  modules/
    platform_admin/  operators, plan catalog, org oversight, metrics   (no RLS)
    auth/            users, sessions, verification/reset tokens        (no RLS)
    tenancy/         organizations (RLS on id), schools
    rbac/            permission catalog, roles, memberships, audit log
    invitations/     send / verify / accept / resend / revoke
    billing/         subscriptions, entitlements, invoices, gateways/
    academics/       classes and sections   (re-keyed onto organization_id)
    students/        student directory      (re-keyed onto organization_id)
  cli.py         seed, seed --demo, reconcile-usage
```

### What is deliberately outside RLS

`permissions`, `plans`, `platform_admins`, `platform_audit_logs`, `webhook_events`,
`users`, `sessions`, `password_reset_tokens`, `email_verification_tokens`.

Each is structurally incapable of belonging to one organization: `plans` is served to
the unauthenticated pricing page and referenced by every tenant at once; a webhook
arrives before we know which org it concerns; `permissions` describes what the
software can do, which is identical for every customer.

`users` is the sharp case, and it has two independent reasons. A policy on it would
make login structurally impossible — the query that finds the user runs before any
organization is known, and a policy comparing against an unset GUC matches zero rows.
More fundamentally, a teacher employed by two school groups is one person with one
password (D4); stamping an `organization_id` on them would force either duplicate
accounts per employer or an arbitrary choice of which employer "owns" them.

---

## Testing

```bash
make test          # 72 tests
make check         # lint + typecheck + test (what CI runs)
```

Integration tests connect as `sms_app`, so RLS is genuinely exercised. A suite running
as `postgres` would pass against a schema with no policies at all.

Fixtures build organizations by driving the **public API** — register, verify, create
school — rather than by inserting rows. Every test therefore re-verifies signup and
provisioning, and no fixture can construct a state the application itself could not
produce.

Coverage of the release gates in spec §12:

| Area | Gates |
|---|---|
| Isolation | cross-org reads 404 not 403; unbound session sees zero rows; `WITH CHECK` blocks cross-tenant writes; platform admin reads but cannot write; every `NOT NULL organization_id` table has forced RLS |
| Authorization | escalation, locked roles, scope crossing, last owner, self-modification, role-in-use 409, permission change effective on the next request |
| Invitations | single use (410), expiry (410), email mismatch (403), `max_staff` 402 *before* the email is sent, resend rotates the token |
| Billing | free plan blocked at school #2 (402), downgrade keeps data readable, duplicate webhook processed once, bad signature rejected |
| Auth | refresh reuse revokes the whole family, 6th failed login locks, unknown vs known email indistinguishable in body **and timing**, reset revokes all sessions |

---

## Commands

| | |
|---|---|
| `make dev` | API with hot reload on :8000 |
| `make test` / `make check` | tests / full quality gate |
| `make migrate` / `make migration m="…"` | apply / generate migrations |
| `make seed` / `make seed-demo` | baseline data / demo organization |
| `make reconcile` | recompute usage counters from source tables |
| `make openapi` | regenerate `openapi.json` (frontend types come from it) |
| `make db-reset` | **destructive**: drop schema, re-migrate, re-seed |

---

## Operational notes

**Adding a tenant table.** Add `TenantMixin`, register the model in
`app/db/registry.py`, call `setup_tenant_table("your_table")` in the migration.
Autogenerate does **not** emit RLS. `test_every_tenant_table_has_forced_rls` fails if
you forget — it exists to catch the table nobody wrote a test for, which is precisely
the one that would leak.

**Usage counters drift.** Entitlement checks read materialised counters rather than
`COUNT(*)`, because the check must be atomic with the insert — a count-then-insert
lets two concurrent requests both pass a limit of one, which is what a double-clicked
button does. The cost is drift if a write path forgets its increment. `make reconcile`
corrects it; a stale `recomputed_at` on a busy organization is the signal that
something is missing an update.

**Production configuration refuses to boot on:** the placeholder `SECRET_KEY`,
`EMAIL_BACKEND=console` (logs OTPs in plaintext, sends nothing), `PAYMENT_GATEWAY=mock`
(approves every charge), `RS256` without a key pair, `SameSite=None` without `Secure`,
and a `SUPERADMIN_PASSWORD` under 16 characters. Each of these fails silently and
expensively if it reaches production, so each fails loudly at startup instead.
