# EduCloud — Frontend

Next.js 15 (App Router) interface for the FastAPI backend in [`../backend`](../backend).
Implements `educloud-core-spec.md` phases 6–8: marketing site, tenant admin panel,
and platform operator console.

| Concern | Choice |
| --- | --- |
| Framework | Next.js 15 App Router, React 19 |
| Language | TypeScript, `strict`, `typedRoutes` |
| Server state | Server Components for reads, route handlers for writes |
| Styling | Tailwind CSS v4 + shadcn/ui components |
| Forms | React Hook Form + Zod |
| Types | Generated from the backend's OpenAPI schema |
| i18n | `en` / `ur` with RTL, from day one |

---

## Three surfaces, one app

Spec §9 defines three route groups with different auth postures. They are kept
structurally apart, not merely conventionally:

```
src/app/
  (marketing)/     public — landing, pricing, signup, login, invite/accept
  (app)/           tenant admin panel — requires a validated session
  platform/        operator console — separate login, separate cookies, dark chrome
```

`platform/` is a real path segment rather than a route group, because it needs its
own URL prefix. Its session lives in **different cookies** from the tenant app
(`educloud_platform_*` vs `educloud_*`), which is what makes spec §9's "unreachable
with a tenant token and vice versa" structural instead of a check someone can forget.
The backend's `typ` claim is the actual enforcement.

An operator can be signed into both at once — common while debugging a customer
issue — and signing out of one does not sign them out of the other.

---

## The token never reaches the browser

```
Browser ──> Next.js route handler ──> FastAPI ──> PostgreSQL
         (opaque httpOnly cookie)   (Bearer token)
```

The Next.js server is a **confidential client**. It calls FastAPI with
`X-Token-Transport: body`, reads the token pair from the response *headers*, and
stores it in its own httpOnly cookies. The browser holds a cookie it cannot read and
talks only to `/api/bff/*`.

So a token is never in `localStorage`, never in a JSON body a script can see, and
never in the browser bundle. An XSS payload here cannot exfiltrate a session — it can
only ride along on requests while the tab is open, which is a far smaller blast
radius.

**Reads bypass the BFF.** A Server Component is already on the server and already has
the session; routing its request out to `/api/bff/*` and back would be a pointless
round trip through this app's own process. So server components call
`serverGet()` (which uses `fetchWithSession`), and client components call the BFF.
One session, two entry points, one copy of the refresh logic.

**Token-minting endpoints are not proxyable.** `auth/login`, `auth/refresh`,
`auth/context` and `invitations/accept` are on the BFF's blocklist — proxying them
would hand raw tokens to client JS. Each has a dedicated handler under `/api/auth/*`
that keeps them server-side.

---

## Permissions

```tsx
<Can permission="member:invite">
  <Button>Invite staff</Button>
</Can>
```

**UI hiding is cosmetic only** (spec §9). Every check maps to a `require("...")`
dependency on the server, which is what actually enforces access. Hiding a button the
API would reject keeps the interface honest about what the user can do; it keeps
nobody out.

Checks are **permission strings, not role names**. Customers create custom roles —
"Head of Year", "Registrar" — and `role === "school_admin"` cannot express them. It
would force every school wanting a different job title to be handed the full admin
role, which is how least-privilege quietly stops being practised.

The permission set arrives once from `GET /auth/me` in the app-group layout and is
published through `<SessionProvider>`. Fetching it per component would render the nav
with no permissions and then rebuild it — which reads as broken even though it
settles correctly.

---

## Context switching

A person can be a teacher at one school and an accountant at another. The header
switcher calls `POST /auth/context`, which **re-issues the token** scoped to the
chosen membership — the permission set, the school scope and the RLS organization all
change with it. The server genuinely starts answering as that person in that place.

That is why switching goes through a route handler and then `router.refresh()`,
rather than setting client state: the source of truth is an httpOnly cookie, and a
client that "remembered" a different context than the cookie carries would show one
school's chrome around another school's data.

Login has a matching case. A user with several memberships gets
`select_required: true` and **no session yet** — not an error, just an unanswered
question. Guessing would drop a teacher into the wrong school's data.

---

## i18n and RTL

`en` and `ur`, wired on day one because spec §9 is explicit that retrofitting RTL
costs 3× more. The expensive part is never the translation files — it is that a
codebase written without RTL accumulates thousands of directional assumptions
(`ml-4`, `text-left`, `border-r`) that all have to be found and converted.

So: `dir` is set on `<html>` from the resolved locale, and every directional utility
in this codebase is **logical** (`ms-*`, `pe-*`, `text-start`, `border-e`). Components
need no locale-aware styling at all.

The Urdu catalog is intentionally partial — its type is derived from the English one,
so a missing key is a compile error, and untranslated entries hold their English text
rather than blocking the build.

---

## Quick start

```bash
npm install
cp .env.example .env.local     # then set API_BASE_URL

npm run dev                    # http://localhost:3000
npm run typecheck
npm run build
```

The backend must be running and seeded (`make seed` in `../backend`) — the pricing
page reads `GET /public/plans`, and signup needs the free plan to exist.

### Regenerating API types

```bash
cd ../backend && make openapi
cd ../frontend && npm run gen:api
```

`src/lib/api/schema.d.ts` is **generated — never edit it**. A renamed backend field
becomes a TypeScript error at the call site that reads it, which is the entire point.
Backend CI fails if `openapi.json` is stale, so the two cannot drift silently.

Generation runs with `--default-non-nullable false`: without it, backend fields that
have defaults are typed as *required* in request bodies, and every form would have to
resend values the server already knows.

---

## Layout

```
src/
  app/
    (marketing)/   landing, pricing, auth forms, invite/accept
    (app)/         dashboard, schools, members, roles, invitations,
                   billing, settings, audit, students, classes
    platform/      operator console
    api/
      auth/        login, context, logout, register, accept-invite   (mint sessions)
      platform/    operator login/logout
      bff/         the proxy for everything else
  components/
    auth/          <Can>, context picker, auth card
    layout/        app shell, sidebar, context switcher, banners
    rbac/          permission matrix, role form
    billing/       usage bars
    platform/      console chrome
    ui/            shadcn primitives
  lib/
    api/           client, server fetchers, generated schema, typed resources
    auth/          session (cookies, refresh, guards), permissions
    i18n/          locale config, catalogs, server resolver
  middleware.ts    edge routing for the three groups
```

---

## Notes worth knowing

**Middleware is a redirect, not a guard.** It runs on the edge with no ability to
verify a signature — it only sees whether a cookie *exists*. Real enforcement is the
backend's `require(...)`, and server components re-verify through `requireUser()` /
`requirePlatformAdmin()`, which do validate the token. Forging a cookie with the right
name gets you past middleware and precisely nowhere else.

**The BFF sends bodies as text.** Next.js instruments `fetch`, and binary body types
(`ArrayBuffer`, `Uint8Array`) do not survive that wrapper — the request arrives with
correct headers and no body. Bodies are also buffered rather than streamed, because
the 401-refresh-retry replays the request and a stream can only be read once. Adding
file uploads means a streaming path and rethinking the retry alongside it.

**`typedRoutes` is on.** Link targets are checked against the real `app/` tree, so a
renamed page cannot leave a dead link. Runtime paths (a `?next=` redirect) need an
explicit `as Route` cast — and are validated as same-origin first, since an
unvalidated redirect target is an open redirect no type could catch.

**Plan-limit failures are 402, not 403.** The user is entitled to the action; they
have run out of what they paid for. The API returns the limit, current usage and an
upgrade URL, and the UI renders an upgrade prompt rather than something that reads
like a bug.
