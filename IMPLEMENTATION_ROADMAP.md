# EduCloud implementation status and delivery guide

Last audited: 2026-08-20

This document tracks implementation against `educloud-core-spec.md`. The core spec
is the source of truth for product behavior; this file records what the repository
currently does, which gaps are release blockers, and the order in which to close
them.

## Executive status

The project is not a blank starter. It already has a substantial FastAPI/PostgreSQL
foundation and a broad Next.js interface. Organization RLS, scoped memberships,
RBAC escalation guards, invitations, plan entitlements, MockGateway billing, the
marketing surface, tenant shell, and platform shell are present.

It is not release-ready yet. Several foundational journeys are broken or only
partially secured. Those defects must be closed before adding attendance, gradebook,
fees, timetable, LMS, or other academic modules.

The first hardening slice completed during this audit is school-scope isolation for
classes, sections, and students. A school-scoped token now receives an automatic
`school_id` predicate from the shared repository, custom academic aggregates apply
the same filter, and a PostgreSQL integration test exercises cross-school list,
read, update, and delete attempts. Organization owners intentionally retain
cross-campus visibility.

## Verification baseline

At the end of the audit:

- Backend Ruff lint and format checks pass.
- Backend strict mypy passes for all 84 application source files.
- The complete backend suite passes: 82 tests against a real PostgreSQL instance.
- Frontend `npm run typecheck` passes.
- Frontend `npm run build` passes and produces all 25 application routes.
- Frontend lint is not a usable gate yet: `next lint` launches interactive setup.
- No frontend unit, integration, or browser test suite exists.

## Phase-by-phase status

| Spec phase | Status | What exists | What remains |
| --- | --- | --- | --- |
| 0. Repository and infrastructure | Partial | Backend Docker Compose, Alembic, environment template, structured logging, backend CI | Full-stack Compose including web, startup migrations, frontend CI, non-interactive lint, deliberate PostgreSQL 16/18 decision |
| 1. Authentication | Partial | Registration, verification, Argon2, access/refresh tokens, rotation and reuse detection, password reset, lockout | Multi-membership continuation, real platform MFA, rate limits, complete auth audit coverage, safe frontend refresh boundary |
| 2. Organizations and RLS | Strong, hardening needed | Forced organization RLS, restricted app role, tenant GUCs, cross-tenant release tests | Contain `role_permissions` DML and verify every indirect tenant table |
| 3. Schools and RBAC | Strong | Schools, memberships, permission catalog, system roles, central `require()`, escalation guards | Complete foundation UI actions and add broader same-org/cross-school tests as modules are added |
| 4. Invitations | Strong, hardening needed | Send/list/resend/revoke, both acceptance branches, token expiry/reuse/email mismatch tests | Rate limiting, counter reconciliation consistency, end-to-end browser tests |
| 5. Plans and billing | Partial | Seeded plans, public catalog, subscriptions, entitlements, usage row, MockGateway, webhook idempotency ledger | Correct webhook tenant resolution, request idempotency keys, invoice download, lifecycle workers, retention/anonymization, real gateway after provider choice |
| 6. Marketing and onboarding | Partial | Landing, pricing, signup, login, verification, invite acceptance, onboarding screens | Anonymous forgot/reset/admissions transport, signup plan selection, automatic switch into first-school principal context, browser journey tests |
| 7. Tenant admin panel | Partial | Dashboard, schools, members, roles matrix, invitations, billing, settings, audit, extra academic prototypes | School edit/archive, role metadata update, ownership transfer, billing cycles/downloads, audit pagination, explicit read-only UI |
| 8. Platform console | Partial | Separate login/cookies, metrics, organization listing/status, plan CRUD and impact | Verified TOTP, organization detail/override, real read-only impersonation, platform audit screen, server-side logout revocation |
| 9. Hardening | Early | Request IDs, structured errors, core security tests | Rate limiting, audit coverage report, background jobs, cursor pagination, frontend E2E, load test, backup/restore drill |

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

### 2. Multi-membership authentication continuation

Problem: when login finds several memberships and none is primary, it returns no
session. `/auth/context` requires an authenticated claim, so a fresh user cannot
complete the selection.

Recommended design:

1. After password verification, mint a short-lived, single-purpose pre-context
   token containing only user ID, session ID, type `context_selection`, and expiry.
2. Store its opaque/hashed continuation in a session row with no membership.
3. Permit only `/auth/context`, `/auth/logout`, and refresh rejection with this token.
4. On selection, verify membership ownership, rotate the continuation, and issue the
   normal membership-scoped token pair.
5. Never allow a pre-context token through tenant `require()` dependencies.

Release gate:

- A fresh multi-membership login can select a context with no prior cookies.
- A continuation cannot call `/auth/me` or any tenant resource.
- Selecting another user's membership fails without revealing its existence.
- Continuations expire, are single-use, and cannot be replayed.
- Frontend login and context picker complete the journey.

### 3. Public frontend request boundary

Problem: forgot password, reset password, and public admissions currently use the
authenticated BFF. With no cookies, the BFF returns 401 before FastAPI is contacted.

Recommended design:

1. Add dedicated, allowlisted Next.js route handlers for public mutations.
2. Each handler calls exactly one corresponding FastAPI public endpoint.
3. Do not turn the generic BFF into an open unauthenticated proxy.
4. Preserve backend problem details and request IDs.
5. Add request throttling at the backend; browser-side throttling is cosmetic.

Release gate:

- Signed-out forgot/reset/admission submissions reach FastAPI.
- Arbitrary tenant paths remain inaccessible without a session.
- Forgot-password responses remain indistinguishable for known and unknown emails.

### 4. Payment webhook tenant binding

Problem: a payment webhook starts with no tenant and queries an RLS-protected
subscription. A valid provider reference therefore resolves as missing and billing
state is not updated.

Recommended design:

1. Verify the webhook signature and store the raw, idempotent event first.
2. Resolve the subscription reference in a narrowly scoped cross-tenant read.
3. Immediately disarm platform-read mode and bind the resolved organization.
4. Apply all subscription, payment, invoice, organization-status, and audit writes
   under that organization's ordinary RLS context.
5. Treat an unknown reference as an inert, retained event rather than a success
   mutation.

Release gate:

- A valid known subscription callback updates exactly one organization.
- Duplicate delivery has one effect.
- Bad signatures and unknown references cannot modify tenant state.
- The cross-tenant read GUC is cleared before every exit path.

### 5. Indirect tenant-table containment

Problem: `role_permissions` has no `organization_id`; an unrestricted app role can
potentially perform direct DML without the parent role's RLS policy protecting it.

Recommended design:

- Prefer database-enforced containment: revoke direct app-role DML on the link table
  and expose narrowly defined security-definer functions that verify the parent
  role belongs to `app.current_org_id`, or remodel the link with an explicit
  organization key and forced RLS.
- Do not rely only on service-layer validation.

Release gate:

- Direct SQL as `sms_app` cannot attach a permission to another tenant's role.
- Normal role-permission replacement still works and increments
  `permissions_version` atomically.

### 6. Platform-admin TOTP MFA

Problem: production currently checks only that an MFA secret exists. It never asks
for or verifies a time-based code.

Recommended design:

- Add enrollment/rotation through a CLI or separately authenticated admin flow.
- Accept a TOTP code during platform login and verify it server-side.
- Encrypt the stored secret with an application-managed key; never return or log it
  after enrollment.
- Use a ±1 time-step tolerance and reject replay of a previously accepted step.

Release gate:

- Missing, invalid, expired, and replayed codes mint no session.
- A valid current code succeeds.
- Tenant login remains independent from the platform MFA surface.

### 7. Auth rate limiting, auditing, and refresh safety

Implement Redis-backed limits for platform login, tenant login, verification resend,
password reset, invitation send/resend, and public admissions. Derive client IP only
from a trusted proxy configuration; do not trust arbitrary `X-Forwarded-For`.

Complete audit events for failed login, lockout, logout, logout-all, reset request,
reset completion, refresh reuse, and platform authentication.

Move refresh rotation out of ordinary Server Component rendering. Cookie mutation
must happen in a route handler or other valid response boundary, and concurrent
expired requests must share one refresh operation rather than replaying a rotated
token.

Release gate:

- The sixth login attempt inside the configured window returns 429.
- Unknown and known accounts remain indistinguishable.
- Every named auth mutation has an audit row.
- Parallel expired frontend requests do not trigger refresh-reuse revocation.

### 8. Entitlement and usage-counter integrity

Define one explicit accounting rule for staff seats. Invitation create, resend,
expiry, revoke, acceptance, member removal, and `reconcile-usage` must all implement
the same rule.

Also:

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

### 9. Billing lifecycle and invoice completion

Add:

- Idempotency-Key handling for money-changing POST requests.
- `GET /billing/invoices/{id}/pdf`, permission-checked and tenant-safe.
- Trial expiry, seven-day past-due grace, suspension, cancel-at-period-end, and
  30-day post-cancellation anonymization jobs.
- Plan-based audit retention jobs.
- Invoice download UI, monthly/yearly selection, and subscribe flow.

Choose and integrate a real gateway only after the product owner selects JazzCash,
Easypaisa, or Stripe and supplies a sandbox contract. Keep the `PaymentGateway` port
and MockGateway contract tests as the shared interface.

### 10. Complete foundation UI and browser tests

Finish school edit/archive, role metadata edit, ownership transfer, billing actions,
audit pagination, platform organization detail, plan override, platform audit logs,
read-only impersonation, and server-side platform logout.

Failures that load permissions or protected page data must fail closed with an
error state. They must not be converted to empty data with destructive controls
still enabled.

Add Playwright coverage for:

- signup → verify → login/context → first school → principal panel;
- both invitation acceptance branches;
- multi-organization and multi-school switching;
- custom role creation and permission revocation;
- plan-limit 402 and suspended read-only behavior;
- platform MFA, suspension, and plan editing;
- English and Urdu directionality.

### 11. Infrastructure and release hardening

- Add the Next.js web service to a root full-stack Compose file.
- Run migrations as an explicit one-shot service before API startup.
- Align PostgreSQL with the spec's version 16 or document and test the intentional
  move to version 18.
- Add frontend CI for clean install, lint, typecheck, build, and browser tests.
- Replace offset pagination with the specified cursor contract or update the spec
  through an explicit architecture decision.
- Add a 1,000-organization load test with stated latency/error SLOs.
- Verify backup restoration and document the drill.

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
npm run typecheck
npm run build
```

After any API contract change:

```bash
cd backend
uv run python scripts/dump_openapi.py
cd ../frontend
npm run gen:api
npm run typecheck
```

