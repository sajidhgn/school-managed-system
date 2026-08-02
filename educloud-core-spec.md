# EduCloud — Multi-Tenant School Management Platform
### Core Spec: Identity, Tenancy, RBAC, Plans & Invitations

**Stack:** Python · FastAPI · PostgreSQL 16 · Next.js (App Router) · TypeScript · TailwindCSS
**Document type:** Build-ready spec / master prompt for a coding agent (Claude Code)
**Scope of this document:** the platform *foundation* only — accounts, tenants, roles, permissions, plans, billing hooks, invitations, admin panel shell. Academic modules (attendance, gradebook, fees, timetable, LMS) are **out of scope here** and live in the separate module spec. Do not build them yet.

---

## 0. Read this first — decisions made for you

These four calls shape every table and endpoint below. If you disagree with any, say so before code is written, because reversing them later is expensive.

**D1 — The tenant is the ORGANIZATION, not the school.**
Your requirement #2 says an owner can create multiple schools. Your requirement #6 says a client buys a plan and enters as principal. Those two only reconcile cleanly if the billing + isolation boundary sits *above* the school. So: `Organization` (the client account) → owns many `Schools`. One subscription per organization; the plan caps how many schools it may create. If you instead want **one subscription per school** (each school billed separately), that is a legitimate alternative — say so and I'll move `subscription.organization_id` to `subscription.school_id` and change the entitlement checks. Everything else survives.

**D2 — "Owner" and "Principal" are different things, and you conflated them.**
Your requirement #3 calls the principal "owner of school." Keep them separate:
- **Owner** = organization-level. Owns billing, creates schools, appoints principals, can see every school in the org. Cannot be removed by anyone below.
- **Principal** = school-level role. Runs one school, manages its roles/permissions, invites teachers and accountants. Has no billing rights and cannot create schools.
On signup, the owner is **auto-granted a Principal membership on the first school they create**, which gives you the behaviour you described in #6 (log in → buy plan → land in the admin panel as principal) without welding the two concepts together. Later, the owner hands Principal to a real employee and keeps owner rights. This is the single most important structural fix in this rewrite.

**D3 — Isolation is Postgres Row-Level Security keyed on `organization_id`, with `school_id` as a scope filter inside it.**
Hard boundary = org (RLS, enforced by the database). Soft boundary = school (enforced by membership + query filter). Rationale: the owner legitimately needs cross-school reads inside their org; a teacher must never escape their school. Two different problems, two different mechanisms. App-layer `WHERE org_id = ?` discipline alone is rejected — one forgotten filter leaks minors' records.

**D4 — Identity is global, membership is scoped.**
One `users` row per human, globally unique email. A human can hold several memberships (teacher at School A, accountant at School B, owner of a different org). The JWT carries **one active membership** at a time; switching context re-issues the token. This is the only sane way to handle a person who works at two client schools, and you *will* hit that case in Pakistan/Gulf private-school groups.

---

## 1. Actors

| Actor | Created by | Lives where | Can do |
|---|---|---|---|
| **Platform Super Admin** | Database seed only. No signup route exists. | Platform tables, outside tenant RLS | Manage plans, view/suspend organizations, impersonate (audited), platform-wide analytics, feature flags |
| **Organization Owner (Client)** | Self-signup from marketing site | Tenant | Buy/change/cancel plan, create schools (up to plan limit), appoint principals, view all schools in org, transfer ownership |
| **Principal** | Auto-assigned to owner on first school; thereafter invited/appointed per school | Tenant, school-scoped | Run the school, create custom roles, assign permissions to roles, invite staff, all school data |
| **Teacher** | Invited by principal | Tenant, school-scoped | Whatever the principal's role config grants |
| **Accountant** | Invited by principal | Tenant, school-scoped | Whatever the principal's role config grants |
| **Custom roles** | Created by principal | Tenant, school-scoped | Any subset of the permission catalog the principal itself holds |

**Explicitly deferred:** Student and Parent portals. They are a different auth surface (often no email, phone-OTP based, guardians linked to multiple children). Do not model them in this phase — you will get it wrong without the student registry existing first.

---

## 2. Tenancy & isolation

### 2.1 Model
```
Platform (no tenant)
└── Organization  (= tenant, RLS key, billing entity)
    ├── Subscription → Plan
    ├── School A
    │   ├── Roles (school-scoped)
    │   └── Memberships (user × school × role)
    ├── School B
    └── Org-level Membership (owner: school_id = NULL)
```

### 2.2 RLS implementation
Every tenant table carries a non-null `organization_id uuid`. Connection-scoped session variables are set by middleware on every request, inside the transaction:

```sql
SET LOCAL app.current_org_id  = '<uuid>';
SET LOCAL app.current_school_id = '<uuid or empty>';
SET LOCAL app.is_platform_admin = 'off';
```

Policy template applied to every tenant table:

```sql
ALTER TABLE schools ENABLE ROW LEVEL SECURITY;
ALTER TABLE schools FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON schools
  USING (
    organization_id = current_setting('app.current_org_id', true)::uuid
    OR current_setting('app.is_platform_admin', true) = 'on'
  )
  WITH CHECK (
    organization_id = current_setting('app.current_org_id', true)::uuid
  );
```

Rules the agent must follow:
- The application connects as a role that is **not** the table owner and **not** `BYPASSRLS`. `FORCE ROW LEVEL SECURITY` is mandatory — without it the owner role silently ignores policies.
- Migrations run as a separate privileged role.
- Platform-admin reads flip `app.is_platform_admin` on **only** inside an explicit, audited impersonation/admin context. Never as a default.
- `WITH CHECK` has no admin escape hatch — a platform admin may read across tenants, not write into them, except through dedicated admin endpoints that set `app.current_org_id` to the target org first.
- Add a test that runs the full CRUD suite as Org A while Org B data exists, asserting zero rows of B ever appear. This test is a release gate.

### 2.3 School scoping
`school_id` is **not** an RLS key. It is enforced in the permission dependency: a request carrying a school-scoped membership gets `WHERE school_id = :active_school_id` injected by a repository-level base query. Owner tokens with `school_id = NULL` skip that filter but remain inside org RLS.

---

## 3. Data model

Use `uuid` PKs (`gen_random_uuid()`), `timestamptz` everywhere, `citext` for email, soft-delete via `deleted_at` on org-visible entities only.

### 3.1 Platform tables (no RLS)

```sql
platform_admins(
  id, email citext UNIQUE, password_hash, full_name,
  is_active bool DEFAULT true, mfa_secret, last_login_at,
  created_at, updated_at
)

plans(
  id, code text UNIQUE,            -- 'free' | 'starter' | 'growth' | 'enterprise'
  name, description, marketing_tagline,
  price_monthly numeric(10,2), price_yearly numeric(10,2), currency char(3),
  trial_days int DEFAULT 0,
  limits jsonb NOT NULL,           -- see §6.2
  features jsonb NOT NULL,         -- feature flags shown on pricing page
  is_public bool DEFAULT true,     -- hidden = enterprise/custom
  is_active bool DEFAULT true,
  sort_order int,
  created_at, updated_at
)

platform_audit_logs(
  id, actor_admin_id, action, entity_type, entity_id,
  target_organization_id, metadata jsonb, ip, user_agent, created_at
)
```

### 3.2 Identity (global, no org column)

```sql
users(
  id, email citext UNIQUE NOT NULL, phone,
  password_hash,                    -- nullable until invite accepted
  full_name, avatar_url, locale DEFAULT 'en', timezone,
  status text DEFAULT 'pending',    -- pending | active | suspended
  email_verified_at, last_login_at,
  failed_login_count int DEFAULT 0, locked_until,
  mfa_enabled bool DEFAULT false, mfa_secret,
  created_at, updated_at
)

sessions(                            -- refresh-token families
  id, user_id, membership_id,
  refresh_token_hash text NOT NULL,  -- sha256, never store raw
  family_id uuid NOT NULL,
  expires_at, revoked_at, revoked_reason,
  ip, user_agent, created_at
)

password_reset_tokens(id, user_id, token_hash, expires_at, used_at, created_at)
email_verification_tokens(id, user_id, token_hash, expires_at, used_at, created_at)
```

### 3.3 Tenant tables (RLS on `organization_id`)

```sql
organizations(
  id, name, slug text UNIQUE, owner_user_id NOT NULL,
  country char(2), timezone, currency char(3), locale,
  status text DEFAULT 'trialing',   -- trialing | active | past_due | suspended | cancelled
  billing_email, tax_id,
  created_at, updated_at, deleted_at
)
-- organizations RLS: id = current_org

subscriptions(
  id, organization_id UNIQUE, plan_id,
  status text,                      -- trialing | active | past_due | cancelled | expired
  billing_cycle text,               -- monthly | yearly
  trial_ends_at, current_period_start, current_period_end,
  cancel_at_period_end bool DEFAULT false, cancelled_at,
  gateway text, gateway_customer_ref, gateway_subscription_ref,
  created_at, updated_at
)

subscription_events(id, organization_id, subscription_id, event_type, from_plan_id, to_plan_id, payload jsonb, created_at)

invoices(
  id, organization_id, subscription_id, number text UNIQUE,
  amount_subtotal, amount_tax, amount_total, currency,
  status,                           -- draft | open | paid | void | uncollectible
  issued_at, due_at, paid_at, gateway_ref, pdf_url, created_at
)

payments(id, organization_id, invoice_id, amount, currency, status, gateway, gateway_ref, raw_payload jsonb, created_at)

schools(
  id, organization_id, name, code text, slug,
  address, city, phone, email, logo_url,
  academic_year_start_month int, timezone, locale,
  status text DEFAULT 'active',     -- active | inactive | archived
  created_at, updated_at, deleted_at,
  UNIQUE(organization_id, code)
)

roles(
  id, organization_id,
  school_id NULL,                   -- NULL = org-level role (owner)
  code text,                        -- 'owner' | 'principal' | 'teacher' | 'accountant' | custom
  name, description,
  is_system bool DEFAULT false,     -- system roles cannot be deleted
  is_editable bool DEFAULT true,    -- owner/principal permission sets are locked
  permissions_version int DEFAULT 1,
  created_at, updated_at,
  UNIQUE(organization_id, school_id, code)
)

permissions(                         -- global catalog, seeded, not tenant data
  code text PRIMARY KEY,            -- 'student:create'
  resource text, action text, category text,
  description, min_scope text,      -- 'org' | 'school'
  is_dangerous bool DEFAULT false
)

role_permissions(role_id, permission_code, PRIMARY KEY(role_id, permission_code))

memberships(
  id, organization_id, user_id,
  school_id NULL,                   -- NULL = org-level (owner)
  role_id NOT NULL,
  status text DEFAULT 'active',     -- active | suspended
  is_primary bool DEFAULT false,
  invited_by_user_id, joined_at,
  created_at, updated_at, deleted_at,
  UNIQUE(user_id, organization_id, school_id) WHERE deleted_at IS NULL
)

invitations(
  id, organization_id, school_id NULL, role_id,
  email citext NOT NULL, full_name,
  token_hash text NOT NULL,          -- sha256 of the raw token
  status text DEFAULT 'pending',     -- pending | accepted | expired | revoked
  expires_at NOT NULL, invited_by_user_id,
  accepted_at, accepted_user_id, resent_count int DEFAULT 0, last_sent_at,
  created_at,
  UNIQUE(organization_id, school_id, email) WHERE status = 'pending'
)

audit_logs(
  id, organization_id, school_id, actor_user_id, actor_membership_id,
  action, entity_type, entity_id,
  before jsonb, after jsonb, ip, user_agent, created_at
)
```

### 3.4 Indexes that matter
`memberships(user_id) WHERE deleted_at IS NULL`, `memberships(organization_id, school_id)`, `invitations(token_hash)`, `sessions(refresh_token_hash)`, `sessions(family_id)`, `audit_logs(organization_id, created_at DESC)`, plus a partial index on `organization_id` for every RLS table (policies are evaluated per row — without these your queries degrade badly past a few hundred tenants).

---

## 4. Authentication

### 4.1 Tokens
- **Access token** — JWT, 15 min, `HS256` in dev / `RS256` in prod. Never stored in `localStorage`.
- **Refresh token** — opaque 256-bit random, 30 days, stored **hashed**, rotated on every use, with **reuse detection**: if a token that was already rotated is presented, revoke the entire `family_id` and force re-login. This catches token theft.
- Transport: `httpOnly`, `Secure`, `SameSite=Lax` cookies. `SameSite=None` only if the marketing site and app sit on different registrable domains.

### 4.2 Access token claims
```json
{
  "sub": "user_uuid",
  "typ": "tenant",            // "tenant" | "platform"
  "mid": "membership_uuid",
  "org": "organization_uuid",
  "sch": "school_uuid|null",
  "rol": "principal",
  "pv":  7,                   // role.permissions_version
  "sid": "session_uuid",
  "exp": 1735689600
}
```

**Permissions are not embedded in the JWT.** Only `pv` is. The permission set is loaded from Redis (key `perm:{role_id}:{pv}`, cache-aside from Postgres). When a principal edits a role, `permissions_version` increments and every existing token for that role is instantly stale → permissions re-resolve on the next request. This is the fix for the classic "I revoked a teacher's access and it took 15 minutes to apply" bug. Do not skip it.

### 4.3 Flows

**A. Platform super admin login** — `POST /api/v1/platform/auth/login`. Seeded credentials only; no registration, no password reset by email link (rotate via CLI). MFA required in production. Rate-limited 5/15min per IP+email.

**B. Client signup (marketing → owner)**
1. `POST /api/v1/auth/register` → `{ full_name, email, password, organization_name, country }`
2. Creates `users` (status `pending`) + `organizations` + org-level `roles.owner` + `memberships(school_id=NULL, role=owner)` in **one transaction**.
3. Sends verification email. Login is blocked until `email_verified_at` is set.
4. On verify → user `active`, subscription created on the **free** plan (or `trialing` on the chosen plan for `trial_days`).
5. Redirect to onboarding: **create your first school**.
6. On first school creation → auto-create school-scoped system roles (principal, teacher, accountant) and grant the owner a `principal` membership on that school. Owner lands in the school admin panel. ← this is your requirement #6.

**C. Invite staff (requirement #7)** — see §7.

**D. Login** — `POST /api/v1/auth/login`. Returns the user's membership list. If exactly one → auto-select and issue a scoped token. If several → return a 200 with `{ user, memberships[], select_required: true }` and no access token until `POST /api/v1/auth/context` picks one.

**E. Context switch** — `POST /api/v1/auth/context { membership_id }`. Verifies the membership belongs to `sub`, is `active`, and its org is not suspended. Issues a fresh access token + rotates refresh within the same session family.

**F. Logout** — revoke session row; clear cookies. `POST /api/v1/auth/logout-all` revokes every family for the user.

### 4.4 Non-negotiables
- Argon2id password hashing (`argon2-cffi`), never bcrypt-by-default, never plain SHA.
- Password policy: min 10 chars, zxcvbn score ≥ 3, checked against a breached-password list.
- Account lockout: 5 failures → 15 min lock, exponential thereafter. Login responses must not reveal whether an email exists.
- Every auth mutation writes an `audit_logs` row.
- Timing-safe comparison on all token lookups; look up by hash, never by raw value.

---

## 5. Authorization (RBAC)

### 5.1 Permission catalog
Format `resource:action`. Seed the catalog; roles reference it. Starter set for this phase:

```
# Organization
org:read, org:update, org:delete, org:transfer_ownership
billing:read, billing:manage, invoice:read, invoice:download

# Schools
school:create, school:read, school:update, school:archive

# People & access
member:read, member:invite, member:update, member:suspend, member:remove
role:read, role:create, role:update, role:delete, role:assign_permissions
invitation:read, invitation:resend, invitation:revoke

# Audit
audit:read

# Placeholders wired but unimplemented (academic modules ship later)
student:*, teacher:*, attendance:*, grade:*, fee:*, timetable:*
```

`min_scope = 'org'` permissions (`school:create`, `billing:*`, `org:*`) can only be attached to org-level roles. Attempting to grant them to a school-scoped role must return `422`.

### 5.2 System roles seeded per school
| Role | Editable | Default permissions |
|---|---|---|
| `owner` (org-level) | No | Everything, including `billing:manage`, `school:create`, `org:transfer_ownership` |
| `principal` | No | All school-scoped permissions + `role:*`, `member:*`, `invitation:*`, `audit:read`. **No** `billing:*`, **no** `school:create` |
| `teacher` | Yes | `member:read`, plus academic reads/writes when those modules land |
| `accountant` | Yes | `member:read`, `invoice:read`, plus fee module when it lands |

### 5.3 The escalation guard — the part that gets built wrong
Requirement #3 lets a principal assign permissions to roles. Three invariants must be enforced server-side, not in the UI:

1. **No self-elevation beyond own grant.** A principal may only grant permissions it currently holds. `granted ⊆ actor_permissions`. Violation → `403 PERMISSION_ESCALATION`.
2. **No editing locked roles.** `is_editable = false` on `owner` and `principal`. A principal cannot widen its own role or the owner's.
3. **No scope crossing.** A school-scoped actor may only touch roles where `role.school_id = actor.school_id`. An owner may touch any role inside their org but still cannot grant an org-scoped permission to a school role.

Additional invariants:
- The last active `owner` membership of an organization cannot be removed, suspended, or demoted. Ownership transfer is a single atomic operation that promotes the new owner before demoting the old one.
- A user cannot suspend/remove their own membership.
- Deleting a role requires reassigning its members first (`409` with the blocking member count).

### 5.4 Enforcement in FastAPI
One dependency, used on every route. No ad-hoc `if user.role == "principal"` anywhere in the codebase — that check is a bug waiting to happen.

```python
@router.post("/schools/{school_id}/members")
async def invite_member(
    payload: InviteCreate,
    ctx: AuthContext = Depends(require("member:invite")),
):
    ...
```

`require(*codes)` resolves the token → loads the permission set from Redis by `(role_id, pv)` → verifies scope → sets the Postgres session GUCs → returns `AuthContext(user, membership, org_id, school_id, permissions)`. Missing permission → `403 { "error": "forbidden", "required": ["member:invite"] }`.

---

## 6. Plans, subscriptions & entitlements

### 6.1 Seed data (requirement #5)
Managed by the platform super admin, stored in `plans`, served to the marketing site by a **public, unauthenticated** endpoint. Never hardcode these in the frontend.

| | **Free** | **Starter** | **Growth** |
|---|---|---|---|
| Code | `free` | `starter` | `growth` |
| Price / mo | 0 | 29 | 79 |
| Price / yr | 0 | 290 | 790 |
| Trial | — | 14 days | 14 days |
| Schools | 1 | 3 | 10 |
| Students | 50 | 500 | 2,500 |
| Staff seats | 3 | 25 | 100 |
| Custom roles | 0 | 5 | unlimited |
| Storage | 1 GB | 20 GB | 100 GB |
| Support | Community | Email | Priority |
| Custom branding | ✕ | ✕ | ✓ |
| API access | ✕ | ✕ | ✓ |
| Audit log retention | 7 days | 90 days | 365 days |

Plus a hidden `enterprise` plan (`is_public = false`, price `null`, limits `-1` = unlimited) that the super admin assigns manually.

```json
// plans.limits
{ "max_schools": 3, "max_students": 500, "max_staff": 25,
  "max_custom_roles": 5, "storage_mb": 20480, "audit_retention_days": 90 }

// plans.features
{ "custom_branding": false, "api_access": false, "priority_support": false,
  "sso": false, "advanced_reports": false }
```
`-1` means unlimited. Every limit key must exist on every plan — no missing-key fallbacks.

### 6.2 Entitlement enforcement
A single `EntitlementService.check(org_id, key, delta=1)` called **before** any resource-creating write. Counters are read from a materialized `organization_usage` row updated transactionally, not from `COUNT(*)` at request time (that will not hold at scale).

Failure → `402 Payment Required` with `{ "error": "plan_limit_exceeded", "limit": "max_schools", "current": 3, "allowed": 3, "upgrade_url": "/billing/plans" }`. The frontend renders an upgrade prompt, not a generic error.

**Downgrade rule:** never delete data. If an org downgrades below current usage, put the org into `over_limit` — existing records stay readable, new creates are blocked until they are back under the cap or upgrade. Deleting a customer's schools because they downgraded is how you get sued.

### 6.3 Subscription lifecycle
`trialing → active → past_due → suspended → cancelled`, plus `expired`.
- `past_due` after a failed charge: 7-day grace, full access, persistent in-app banner.
- `suspended`: login still works, admin panel is **read-only**, exports remain available. Never lock a school out of its own student records over a payment issue.
- Cancellation is `cancel_at_period_end` by default; immediate cancel is a super-admin action.
- 30-day data retention after cancellation, then anonymize.

### 6.4 Payment gateway
Define a `PaymentGateway` port with `create_customer / create_subscription / change_plan / cancel / handle_webhook`, and implement adapters behind it. Ship a `MockGateway` first so the whole flow is testable without credentials. Given the Pakistan target, the real adapters are **JazzCash** and **Easypaisa**; keep Stripe as an international fallback. Webhooks must be signature-verified, idempotent by `gateway_event_id`, and stored raw before processing.

---

## 7. Invitations (requirement #7)

### 7.1 Send
`POST /api/v1/schools/{school_id}/invitations` — requires `member:invite`.
```json
{ "email": "teacher@school.pk", "full_name": "Ayesha K.", "role_id": "uuid" }
```
Server:
1. Verify `role_id` belongs to this org **and** this school.
2. Verify the actor holds every permission attached to that role (§5.3 rule 1 applies to invites too — otherwise invite becomes an escalation backdoor).
3. `EntitlementService.check(org, "max_staff")`.
4. Reject if an active membership already exists for that email in this school (`409`).
5. Generate `token = secrets.token_urlsafe(32)`; store **only** `sha256(token)`; `expires_at = now + 7d`.
6. Email the link `{APP_URL}/invite/accept?token=<raw>`. The raw token appears exactly once, in that email.
7. Audit log.

Resend: max 5, rate-limited, invalidates the previous token. Revoke: `status = 'revoked'`, token dead immediately.

### 7.2 Accept
`GET /api/v1/invitations/verify?token=...` → public, returns `{ school_name, role_name, email, inviter_name, requires_signup: bool }` and nothing else. Do not leak org internals to an unauthenticated token holder.

`POST /api/v1/invitations/accept` → two branches, both in one transaction:

- **New user** (no `users` row for that email): body carries `{ token, full_name, password }`. Creates `users` (status `active`, `email_verified_at = now()` — the invite email *is* the verification) + `memberships`. No separate verification email.
- **Existing user**: body carries `{ token }` and requires an authenticated session for the same email. Creates only the `memberships` row, then offers a context switch to the new school.

Then: mark invitation `accepted`, set `accepted_user_id`, increment usage counters, audit, issue tokens scoped to the new membership, redirect to the admin panel.

**Guards:** token is single-use (unique constraint on `accepted_user_id` + status check inside the transaction); expired → `410`; the account email must match the invited email exactly — a logged-in user with a different email accepting someone else's invite is a real attack, and it is trivially blocked by this one check.

---

## 8. API surface (v1)

```
# Platform (super admin, seeded)
POST   /platform/auth/login
GET    /platform/organizations                 ?status=&plan=&q=
GET    /platform/organizations/{id}
PATCH  /platform/organizations/{id}/status     suspend | reactivate
POST   /platform/organizations/{id}/plan       manual plan override
POST   /platform/organizations/{id}/impersonate   audited, time-boxed, read-only
GET/POST/PATCH/DELETE /platform/plans
GET    /platform/metrics                       MRR, orgs, churn, seats
GET    /platform/audit-logs

# Public (marketing site)
GET    /public/plans                           cached 5 min, is_public=true only

# Auth
POST   /auth/register
POST   /auth/verify-email
POST   /auth/login
POST   /auth/context
POST   /auth/refresh
POST   /auth/logout
POST   /auth/logout-all
POST   /auth/forgot-password
POST   /auth/reset-password
GET    /auth/me                                user + memberships + active context + permissions

# Organization
GET    /org
PATCH  /org
POST   /org/transfer-ownership
GET    /org/usage                              live counters vs plan limits

# Billing
GET    /billing/subscription
POST   /billing/subscribe          { plan_code, billing_cycle }
POST   /billing/change-plan
POST   /billing/cancel
GET    /billing/invoices
GET    /billing/invoices/{id}/pdf
POST   /webhooks/payments/{gateway}            unauthenticated, signature-verified

# Schools
GET    /schools
POST   /schools                                entitlement-checked
GET    /schools/{id}
PATCH  /schools/{id}
POST   /schools/{id}/archive

# Roles & permissions
GET    /schools/{school_id}/roles
POST   /schools/{school_id}/roles
PATCH  /schools/{school_id}/roles/{role_id}
DELETE /schools/{school_id}/roles/{role_id}
PUT    /schools/{school_id}/roles/{role_id}/permissions   { codes: [...] }
GET    /permissions                            catalog, grouped by category

# Members & invitations
GET    /schools/{school_id}/members
PATCH  /schools/{school_id}/members/{id}       change role / suspend
DELETE /schools/{school_id}/members/{id}
POST   /schools/{school_id}/invitations
GET    /schools/{school_id}/invitations
POST   /schools/{school_id}/invitations/{id}/resend
DELETE /schools/{school_id}/invitations/{id}
GET    /invitations/verify                     public
POST   /invitations/accept                     public

# Audit
GET    /schools/{school_id}/audit-logs
```

**Conventions:** envelope-free JSON, `snake_case`, cursor pagination (`?cursor=&limit=`), RFC-7807-ish errors `{ error, message, details }`, `X-Request-ID` on every response, idempotency keys on all POSTs that touch money.

---

## 9. Frontend

Three surfaces, one Next.js repo, separated by route group:

```
app/
  (marketing)/          # public — no auth
    page.tsx
    pricing/            # renders GET /public/plans
    signup/  login/
    invite/accept/
  (app)/                # tenant admin panel — auth required
    onboarding/         # create first school
    dashboard/
    schools/
    members/  roles/  invitations/
    billing/  settings/
  (platform)/           # super admin — separate login, separate layout
    organizations/  plans/  metrics/
```

Rules:
- Middleware guards each route group; the platform group must be unreachable with a tenant token and vice versa (check the `typ` claim).
- `<Can permission="member:invite">` wrapper for conditional UI — **UI hiding is cosmetic only**, every action is re-checked server-side.
- A school switcher in the header when the active membership has more than one school; an org/context switcher when the user has memberships across orgs.
- Server Components for reads, Server Actions or route handlers for writes. Access token stays in an httpOnly cookie; never expose it to client JS.
- i18n scaffolded from day one (`en`, `ur`) with RTL support wired in Tailwind (`dir` attribute + logical properties). Retrofitting RTL later costs 3× more than doing it now.

---

## 10. Build order

Ship each phase behind passing tests before starting the next. Do not build phase 5 features into phase 2.

| Phase | Deliverable | Done when |
|---|---|---|
| **0** | Repo, Docker Compose (Postgres + Redis + API + web), Alembic, CI, `.env.example`, structured logging | `docker compose up` boots the stack clean |
| **1** | Users, sessions, Argon2, JWT + refresh rotation with reuse detection, email verification, password reset | Auth test suite green |
| **2** | Organizations, RLS policies + `FORCE`, session GUC middleware, cross-tenant isolation test | Org A cannot see a single row of Org B |
| **3** | Schools, memberships, permission catalog, system roles, `require()` dependency, escalation guards | All §5.3 invariants have failing-then-passing tests |
| **4** | Invitations end-to-end incl. both accept branches + expiry/reuse/email-mismatch cases | An invited teacher can log into the panel |
| **5** | Plans, seeds, `/public/plans`, subscriptions, entitlements, MockGateway, webhooks | Free-plan org is blocked at school #2 with a 402 |
| **6** | Marketing site + pricing page + signup + accept-invite page | Signup → verify → school → panel, unbroken |
| **7** | Admin panel: dashboard, members, roles matrix editor, invitations, billing, settings | Principal can build a custom role in the UI |
| **8** | Platform super-admin console + seed CLI | Super admin can suspend an org and edit plans |
| **9** | Hardening: rate limits, audit coverage, OpenAPI docs, load test at 1k orgs | Release gate |

---

## 11. Seeds

`python -m app.cli seed` — idempotent, safe to re-run.
1. Permission catalog (§5.1).
2. Plans: free, starter, growth, enterprise (§6.1).
3. One platform super admin from `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` env vars. **Refuse to run in production if the password is the default or shorter than 16 chars** — abort with a non-zero exit.
4. `--demo` flag only: one demo org, two schools, a principal, two teachers, an accountant, five pending invitations.

---

## 12. Test gates (a phase is not done without these)

**Isolation**
- Org A token reading any Org B endpoint → 404, not 403 (do not confirm existence).
- Direct SQL as the app role without GUCs set → zero rows.
- Teacher of School 1 requesting School 2 in the same org → 403.

**Authorization**
- Principal grants a permission it does not hold → 403.
- Principal edits its own role → 403 (`is_editable = false`).
- School role granted `school:create` (org-scoped) → 422.
- Removing the last owner → 409.
- Role permission change → next request by an affected member uses the new set (no token wait).

**Invitations**
- Same token used twice → second attempt 410.
- Expired token → 410.
- Logged-in user with a different email accepting → 403.
- Invite that exceeds `max_staff` → 402 before the email is sent.

**Billing**
- Free-plan org creating school #2 → 402.
- Downgrade below usage → existing data readable, new creates blocked.
- Duplicate webhook delivery → processed once.

**Auth**
- Reused refresh token → whole family revoked.
- 6th failed login → locked.
- Login response for unknown vs known email is indistinguishable in body and timing.

---

## 13. Out of scope here

Student registry, guardians, admissions, attendance, timetable, gradebook, exams, fees/vouchers, library, transport, hostel, HR/payroll, LMS, AI assistant, parent/student portals, mobile apps, SSO/SAML, offline mode. All of these assume the foundation above exists. Build the foundation first — every one of those modules will hang off `organization_id`, `school_id`, and the permission catalog, and retrofitting them onto a broken tenancy model is a rewrite, not a refactor.
