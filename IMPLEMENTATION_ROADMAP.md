# EduCloud implementation status and delivery guide

Last audited: 2026-08-22

This document tracks implementation against `educloud-core-spec.md`. The core spec
is the source of truth for product behavior; this file records what the repository
currently does, which gaps are release blockers, and the order in which to close
them.

## Executive status

The foundation implementation is complete. The FastAPI/PostgreSQL backend and
Next.js frontend now cover tenant isolation, multi-membership authentication, RBAC,
invitations, entitlement accounting, billing lifecycle/invoices, tenant and platform
administration, audited read-only support access, and full-stack packaging.

No known foundation code defect remains open. Three release-validation items remain:

1. A product owner must select JazzCash, Easypaisa, or Stripe and provide its sandbox
   contract before the real payment adapter can replace `MockGateway`.
2. The four Playwright foundation smoke tests pass, while the larger authenticated
   browser journey matrix listed in slice 10 still needs automation. The underlying
   journeys are covered by PostgreSQL-backed API integration tests.
3. The 1,000-organization k6 profile is checked in, but needs a staging environment,
   k6, and 1,000 scoped test tokens before its SLO result can be recorded.

## Verification baseline

At the end of the foundation implementation:

- Backend Ruff lint and format checks pass for 112 Python files.
- Backend strict mypy passes for all 89 application source files.
- The complete backend suite passes: 100 tests against real PostgreSQL.
- Alembic upgrades cleanly to `c9f1a3b5d7e9` (head).
- OpenAPI is regenerated and the frontend schema matches it.
- Frontend ESLint, TypeScript, and the production Next.js 15.5.23 build pass.
- Full `npm audit` reports zero production or development vulnerabilities.
- Four Playwright foundation smoke tests pass serially against live local servers.
- Root Compose validates and the standalone production web image builds.
- A real dump/restore drill passed; the restored drill database is retained for
  inspection.
- The sample invoice PDF rendered as a valid one-page A4 document and passed visual
  inspection.

## Phase-by-phase status

| Spec phase | Status | What exists | What remains |
| --- | --- | --- | --- |
| 0. Repository and infrastructure | Implemented | Root full-stack Compose, one-shot migrations, PostgreSQL 16, backend/frontend CI, standalone web image, non-interactive lint | Execute the checked-in staging load profile |
| 1. Authentication | Implemented | Registration/verification, multi-membership continuation, Argon2, safe refresh rotation, lockout, Redis limits, complete auth auditing, platform TOTP | Expanded authenticated browser automation |
| 2. Organizations and RLS | Implemented | Forced organization RLS, restricted app role, tenant GUCs, indirect `role_permissions` containment, cross-tenant tests | Continue the same pattern for future modules |
| 3. Schools and RBAC | Implemented | Schools, scoped memberships, central permissions, escalation guards, role editing, ownership transfer, isolation tests | Future academic modules are out of core scope |
| 4. Invitations | Implemented | Both acceptance branches, expiry/reuse/email guards, throttling, reconciliation, scheduled seat release | Expanded browser automation |
| 5. Plans and billing | Implemented with external adapter pending | Plans, entitlements, tenant-bound webhooks, request idempotency, PDF invoices, lifecycle/retention jobs, billing UI | Select and integrate a real provider sandbox |
| 6. Marketing and onboarding | Implemented | Fixed anonymous handlers, signup plan/cycle intent, verification, automatic principal context after first school | Expanded browser automation |
| 7. Tenant admin panel | Implemented | School/role/member/billing/audit/settings actions, cursor audit pagination, read-only support mode | Expanded browser automation |
| 8. Platform console | Implemented | TOTP, organization detail/status/override, audited support view, audit screen, revoking logout | Expanded browser automation |
| 9. Hardening | Implemented; staging evidence pending | Rate limits, audit coverage, maintenance jobs, pagination ADR, Playwright smoke, load profile, restore drill, clean production dependency audit | Run the 1,000-organization profile in staging |

## Delivery order

Work through these slices in order. Each slice has a release gate and should be
merged only when its tests pass.

### 1. School-scope isolation hardening — completed

Problem: organization RLS correctly prevents Org A from seeing Org B, but RLS is
intentionally not keyed by school. Without a repository predicate, staff at School A
could see or mutate School B academic rows inside the same organization.

Implemented:

- Inject the active membership's `school_id` into generic repository selects,
  existence checks, counts, soft deletes, and hard deletes.
- Skip that filter for an organization-level owner.
- Scope custom student headcount queries.
- Scope public admission-number generation to the verified target school.
- Allow test database host and port overrides so an isolated database can be used.
- Add a real PostgreSQL regression covering classes, sections, and students.

Release gate:

- A School A principal sees only School A academic rows.
- Known School B resource IDs return 404 for reads and mutations.
- Failed cross-school mutations leave School B rows unchanged.
- An organization owner can still read both schools.

### 2. Multi-membership authentication continuation — implemented, browser coverage pending

Problem: when login finds several memberships and none is primary, it returns no
session. `/auth/context` requires an authenticated claim, so a fresh user cannot
complete the selection.

Implemented:

- Password login with no primary membership mints a five-minute access token of type
  `context_selection`, backed by a membership-less session row whose refresh secret
  is never returned.
- The Next.js login handler stores this credential in an httpOnly access cookie and
  stores no refresh cookie until selection succeeds.
- Tenant routes and `/auth/me` reject the continuation; `/auth/context` verifies
  membership ownership and consumes it before issuing the normal scoped token pair.
- Replays and expired/revoked continuations fail, and context-only sessions cannot
  use refresh or session-management endpoints.
- Backend integration coverage exercises selection, tenant-route rejection, missing
  refresh credentials, successful scoping, and replay rejection.

Release gate:

- A fresh multi-membership login can select a context with no prior cookies.
- A continuation cannot call `/auth/me` or any tenant resource.
- Selecting another user's membership fails without revealing its existence.
- Continuations expire, are single-use, and cannot be replayed.
- Frontend login and context picker complete the journey; automated browser coverage
  remains part of slice 10.

### 3. Public frontend request boundary — implemented, browser coverage pending

Problem: forgot password, reset password, and public admissions currently use the
authenticated BFF. With no cookies, the BFF returns 401 before FastAPI is contacted.

Implemented:

- Dedicated Next.js handlers expose only forgot-password, reset-password, and
  admissions; each forwards to one fixed FastAPI endpoint.
- The generic BFF explicitly blocks those paths and remains authenticated for every
  other tenant request.
- Backend problem bodies, status codes, request IDs, and retry headers are preserved.
- The three signed-out forms now use the dedicated handlers. Runtime checks cover
  anonymous success/error transport and generic-proxy rejection.
- Backend request throttling remains consolidated in slice 7 so all sensitive auth
  and public endpoints share one policy and trusted-proxy model.

Release gate:

- Signed-out forgot/reset/admission submissions reach FastAPI; automated browser
  coverage remains part of slice 10.
- Arbitrary tenant paths remain inaccessible without a session.
- Forgot-password responses remain indistinguishable for known and unknown emails.

### 4. Payment webhook tenant binding — completed

Problem: a payment webhook starts with no tenant and queries an RLS-protected
subscription. A valid provider reference therefore resolves as missing and billing
state is not updated.

Implemented:

- Webhook signatures are verified before an idempotent raw event is inserted.
- Subscription references resolve under a narrowly scoped cross-tenant read that is
  cleared on every exit path.
- Known events bind the resolved organization before all tenant writes; unknown
  references are retained and inert.
- Integration coverage verifies exact-tenant mutation, duplicate delivery, bad
  signatures, unknown references, and privileged-GUC cleanup.

Release gate:

- A valid known subscription callback updates exactly one organization.
- Duplicate delivery has one effect.
- Bad signatures and unknown references cannot modify tenant state.
- The cross-tenant read GUC is cleared before every exit path.

### 5. Indirect tenant-table containment — completed

Problem: `role_permissions` has no `organization_id`; an unrestricted app role can
potentially perform direct DML without the parent role's RLS policy protecting it.

Implemented:

- `role_permissions` now carries `organization_id` with forced RLS.
- A composite foreign key to `(roles.id, roles.organization_id)` prevents the tenant
  key from disagreeing with its parent role.
- Provisioning and normal role updates populate the tenant key, with integration
  coverage for raw cross-tenant DML rejection and ordinary permission replacement.

Release gate:

- Direct SQL as `sms_app` cannot attach a permission to another tenant's role.
- Normal role-permission replacement still works and increments
  `permissions_version` atomically.

### 6. Platform-admin TOTP MFA — completed

Problem: production currently checks only that an MFA secret exists. It never asks
for or verifies a time-based code.

Implemented:

- `make mfa-enroll email=...` enrolls or rotates a standard authenticator secret and
  prints it once.
- Secrets are encrypted using an application-key-derived Fernet key; platform login
  accepts and verifies a six-digit code server-side.
- Verification uses ±1 time step and persists the last accepted counter to reject
  replay. The frontend platform login includes one-time-code entry.
- Integration coverage verifies missing, invalid, valid, and replayed codes.

Release gate:

- Missing, invalid, expired, and replayed codes mint no session.
- A valid current code succeeds.
- Tenant login remains independent from the platform MFA surface.

### 7. Auth rate limiting, auditing, and refresh safety — implemented

Implemented Redis-backed limits for platform login, tenant login, verification
resend, password reset, invitation send/resend, and public admissions. Client IP is
derived only through the trusted-proxy configuration; arbitrary forwarded headers
are not trusted.

Audit events cover failed login, lockout, logout, logout-all, reset request/reset
completion, refresh reuse, and platform authentication/logout.

Refresh rotation now occurs only at a writable response boundary. Concurrent
expired requests share one in-process rotation promise keyed by the credential
digest, preventing replay revocation.

Release gate:

- The sixth login attempt inside the configured window returns 429.
- Unknown and known accounts remain indistinguishable.
- Every named auth mutation has an audit row.
- Parallel expired frontend requests do not trigger refresh-reuse revocation.

### 8. Entitlement and usage-counter integrity — implemented

Staff accounting uses one rule across invitation create, expiry, revoke, acceptance,
member removal, and `reconcile-usage`. Maintenance now expires abandoned invitations
under normal tenant RLS and releases their reserved seats in the same transaction.

Also implemented:

- Release student capacity on active-to-inactive transitions and soft deletion.
- Consume capacity on reactivation.
- Mark an organization over-limit only when `current > allowed`, not when equal.
- Bind each organization normally before reconciliation writes.
- Add concurrency tests for seat reservation.

Release gate:

- Reconciliation is idempotent and matches live counters.
- Expired/revoked invitations cannot leak capacity.
- Exact-at-limit is valid; only above-limit is flagged.
- Concurrent creates cannot exceed the plan.

### 9. Billing lifecycle and invoice completion — implemented except external adapter

Implemented:

- Idempotency-Key handling for money-changing POST requests.
- `GET /billing/invoices/{id}/pdf`, permission-checked and tenant-safe.
- Trial expiry, seven-day past-due grace, suspension, cancel-at-period-end, and
  30-day post-cancellation anonymization jobs.
- Plan-based audit retention jobs.
- Invoice download UI, monthly/yearly selection, and subscribe flow.

The provider-neutral `PaymentGateway` port and MockGateway contract tests remain the
shared interface. Real integration is intentionally blocked until the product owner
selects JazzCash, Easypaisa, or Stripe and supplies its sandbox contract.

### 10. Complete foundation UI and browser tests — UI implemented, matrix pending

Implemented school edit/archive, role metadata edit, ownership transfer, billing
actions, audit pagination, platform organization detail, plan override, platform
audit logs, audited time-boxed read-only support access, and server-side platform
logout.

Failures that load permissions or protected page data must fail closed with an
error state. They must not be converted to empty data with destructive controls
still enabled.

Current Playwright coverage verifies the anonymous password-reset handler, generic
BFF blocking, English/Urdu direction, and the platform credential/MFA surface. The
complete PostgreSQL-backed API suite covers the underlying authentication,
invitation, switching, RBAC, billing-limit, suspension, and platform mutations.

Still add browser-level automation for:

- signup → verify → login/context → first school → principal panel;
- both invitation acceptance branches;
- multi-organization and multi-school switching;
- custom role creation and permission revocation;
- plan-limit 402 and suspended read-only behavior;
- platform MFA, suspension, and plan editing;
- English and Urdu directionality.

### 11. Infrastructure and release hardening — implemented, load execution pending

- Root Compose includes PostgreSQL 16, Redis, an explicit one-shot migration service,
  FastAPI, and the standalone Next.js web image.
- Frontend CI performs clean install, lint, typecheck, build, and Playwright tests.
- ADR 0001 records the deliberate hybrid cursor/offset pagination contract.
- `tests/load/k6-1000-organizations.js` defines p95 < 500 ms, p99 < 1 s, and error
  rate < 1% thresholds; execution awaits staging tokens and k6.
- The documented dump/restore drill passed and its restored database is retained.

## Remaining foundation release validation

These are the only items still open; none is an unimplemented core backend or UI
feature:

1. Product decision and sandbox credentials for the real payment gateway adapter.
2. The expanded authenticated Playwright journey matrix in slice 10.
3. A recorded staging run of the checked-in 1,000-organization k6 profile.

## Guidance for every future school module

The current core spec explicitly defers attendance, gradebook, fees, timetable,
library, transport, HR/payroll, LMS, parent/student portals, and mobile apps. A
separate academic module specification is not present in this repository. Do not
guess those workflows from table names; agree the module behavior first.

Every new tenant-owned module must follow this checklist:

1. Carry non-null `organization_id` and the correct nullable/non-null `school_id`.
2. Add forced RLS in an Alembic migration; autogenerate does not create policies.
3. Use the restricted application role in integration tests.
4. Route every read and mutation through `require("resource:action")`.
5. Use repository-level school scoping and explicitly scope custom SQL/aggregates.
6. Take tenant/school identifiers from the verified context, never a writable body.
7. Enforce plan capacity transactionally before creating metered resources.
8. Record mutations in the same transaction as their audit event.
9. Return 404 for inaccessible foreign resources when existence must be hidden.
10. Add two-organization and two-school CRUD isolation tests before UI work.
11. Add generated OpenAPI types and a browser journey before declaring completion.
12. Define retention, export, soft-delete, and restoration behavior up front.

For an academic module specification, document at minimum: actors, permissions,
states and transitions, required fields, uniqueness rules, school-year behavior,
bulk operations, reports/exports, notification side effects, plan limits, audit
events, retention, and acceptance tests.

## Routine verification commands

Backend (requires PostgreSQL with migrations and seeds):

```bash
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.cli seed
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest --cov --cov-report=term-missing
```

Frontend:

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
npm run test:e2e
```

After any API contract change:

```bash
cd backend
uv run python scripts/dump_openapi.py
cd ../frontend
npm run gen:api
npm run typecheck
```
