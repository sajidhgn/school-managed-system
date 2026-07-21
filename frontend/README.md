# Frontend — School Management System

Next.js 15 (App Router) admin interface for the FastAPI backend in [`../backend`](../backend).

| Concern | Choice |
| --- | --- |
| Framework | Next.js 15 App Router, React 19 |
| Language | TypeScript, `strict` |
| Server state | TanStack Query v5 |
| Styling | Tailwind CSS v4 + shadcn/ui components |
| Forms | React Hook Form + Zod |
| Types | Generated from the backend's OpenAPI schema |

---

## The frontend does not touch PostgreSQL

It has no database driver and no connection string. Every read and write goes
through the FastAPI API, because the backend is where the rules live:

- **JWT authentication** — who is asking
- **`require_roles(...)`** — whether they may
- **Row-Level Security** — which tenant's rows they can even see
- **Pydantic validation** — whether the payload is legal

A direct database connection from the browser or from Next.js would bypass all
four. The data flow is:

```
Browser ──> Next.js route handler (/api/bff/*) ──> FastAPI ──> PostgreSQL
            attaches the Bearer token             enforces auth,
            from an httpOnly cookie               RLS, validation
```

### Why the proxy exists

The browser never holds a token. `POST /api/auth/login` forwards credentials to
FastAPI and stores the returned token pair in **httpOnly** cookies, which client
JavaScript cannot read. Every subsequent request goes to `/api/bff/*`, which
attaches the `Authorization` header server-side and transparently refreshes an
expired access token before retrying once.

The practical consequence: an XSS bug in this app cannot exfiltrate a school
admin's session token.

---

## Setup

### 1. Install

```bash
npm install
cp .env.example .env.local
```

`.env.local` values are server-side only — there is deliberately no
`NEXT_PUBLIC_` API URL, since the browser never calls FastAPI directly.

### 2. Connect the backend to PostgreSQL

The backend ships with `DB_ENABLED=false`, which lets it boot and serve
`/health` without a database. Auth and every data route need a real database, so
enable it before using the UI.

```bash
cd ../backend

createdb -U postgres school_manage_db

# Extensions + the restricted app role. Needs a superuser; sms_app must NOT own
# tables, or it would silently bypass RLS.
psql -U postgres -d school_manage_db -f scripts/init-db.sql

# init-db.sql hardcodes the role password, so align it with .env:
psql -U postgres -d school_manage_db \
  -c "ALTER ROLE sms_app WITH PASSWORD '<your POSTGRES_PASSWORD>';"

make migrate
```

`backend/.env` needs all four of these:

```ini
DB_ENABLED=true
POSTGRES_PASSWORD=<the password you gave sms_app>

# Required. init-db.sql REVOKEs CREATE on public from sms_app, so Alembic
# cannot run as the app role — it must connect as the schema owner. Leaving
# MIGRATION_USER empty makes it fall back to sms_app and `make migrate` fails
# with "permission denied for schema public".
MIGRATION_USER=postgres
MIGRATION_PASSWORD=<postgres password>
```

Docker alternative, if you prefer it to a local PostgreSQL:

```bash
cd ../backend && make docker-up
```

### 3. Run both services

```bash
cd ../backend && make dev     # http://localhost:8000
cd ../frontend && npm run dev # http://localhost:3000
```

The backend's `CORS_ORIGINS` already lists `http://localhost:3000`.

### 4. Create the first super admin

```bash
cd ../backend && uv run python scripts/create_super_admin.py
```

School admins self-register at `/register`; a super admin approves them from
`/schools`.

---

## Keeping types in sync with the API

`src/lib/api/schema.d.ts` is **generated** — never edit it. After any backend
route or schema change:

```bash
cd ../backend  && uv run python scripts/dump_openapi.py
cd ../frontend && npm run gen:api && npm run typecheck
```

A renamed or removed backend field becomes a TypeScript error rather than a
runtime `undefined` in production. `src/lib/api/types.ts` holds readable aliases
over the generated types; the display-label maps there are exhaustive `Record`s,
so a new backend enum variant fails to compile until the UI handles it.

---

## Routes

| Route | Access | Purpose |
| --- | --- | --- |
| `/login` | Public | Sign in, including the 2FA challenge step |
| `/register` | Public | Register a school + its first admin |
| `/verify-email` | Public | Email verification code |
| `/forgot-password`, `/reset-password` | Public | Password reset |
| `/admissions/[schoolId]` | Public | Admission application form for parents |
| `/dashboard` | All roles | Headline numbers and recent activity |
| `/students`, `/students/[id]` | Admin (write), Teacher (read) | Student directory |
| `/classes` | Admin (write), Teacher (read) | Classes and sections |
| `/admissions-queue` | School admin | Approve/reject pending applications |
| `/schools` | Super admin | Onboard, approve, suspend tenants |
| `/settings` | All roles | Profile, school details, theme |

Role checks in `src/lib/auth/permissions.ts` decide what the UI **shows**. They
are not security — each one mirrors a `require_roles(...)` dependency in the
backend, which is what actually enforces access.

---

## Layout

```
src/
  app/
    (auth)/            login, register, verify-email, forgot/reset password
    (dashboard)/       authenticated app — layout re-validates the session
    admissions/        public application form
    api/
      auth/            login/logout/register — mint and clear httpOnly cookies
      bff/[...path]/   authenticated proxy to FastAPI, refreshes on 401
  components/
    ui/                shadcn/ui primitives
    layout/            app shell, sidebar, user menu
  hooks/               TanStack Query hooks, one file per backend module
  lib/
    api/               client, generated schema, typed resources, query keys
    auth/              session cookies, refresh, role helpers
    validation/        Zod schemas mirroring the Pydantic models
  middleware.ts        cheap cookie gate — real enforcement is server-side
```

## Scripts

```bash
npm run dev        # dev server on :3000
npm run build      # production build
npm run typecheck  # tsc --noEmit
npm run gen:api    # regenerate types from ../backend/openapi.json
```
