# School Management System — Backend

Multi-tenant SaaS backend. FastAPI · Pydantic v2 · SQLAlchemy 2.x (async) · Alembic · PostgreSQL.

---

## Quick start

```bash
cd backend
uv venv --python 3.13
uv sync
cp .env.example .env          # then set SECRET_KEY
make dev                      # http://localhost:8000/docs
make check                    # lint + typecheck + tests
```

The application boots and serves `/health` with **no database**. Set `DB_ENABLED=true`
only once PostgreSQL is provisioned.

---

## The architecture in one picture

```
HTTP request
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ MIDDLEWARE      request id, access log, CORS, gzip          │
├─────────────────────────────────────────────────────────────┤
│ ROUTER          app/modules/<m>/router.py                   │
│                 HTTP only: parse, validate, delegate.       │
│                 Never contains business rules.              │
├─────────────────────────────────────────────────────────────┤
│ SERVICE         app/modules/<m>/service.py                  │
│                 Business rules, orchestration, transaction  │
│                 boundaries. Knows nothing about HTTP.       │
├─────────────────────────────────────────────────────────────┤
│ REPOSITORY      app/modules/<m>/repository.py               │
│                 SQL only. Knows nothing about business.     │
├─────────────────────────────────────────────────────────────┤
│ MODEL           app/modules/<m>/models.py                   │
│                 SQLAlchemy tables + constraints.            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
PostgreSQL — Row-Level Security enforces the tenant boundary
```

**The dependency rule:** arrows point *downward only*. A service may import a
repository; a repository may never import a service. A service may never import
`fastapi`. This is what makes services reusable from a CLI, a background worker, or
a test without an HTTP client.

---

## Why a modular monolith (`app/modules/`) rather than flat layers

The FastAPI skill playbook suggests grouping by technical layer — one `models/`
directory, one `services/` directory, and so on. That works well up to roughly ten
tables. This system has eight domains and will reach forty-plus tables, so we group
by **domain** instead, with the layers *inside* each module:

```
app/modules/students/
├── models.py       ORM tables
├── schemas.py      Pydantic request/response contracts
├── repository.py   data access
├── service.py      business rules
└── router.py       HTTP endpoints
```

Why this scales better here:

- **Change locality.** "Add a guardian phone number" touches five files in one
  directory, not five files scattered across five directories.
- **Reviewable boundaries.** An import of `modules.finance` from inside
  `modules.students` is visible in a diff and can be challenged. With flat layers,
  cross-domain coupling is invisible.
- **Extraction path.** If the AI Marketing Studio ever needs to become its own
  service (different scaling profile, GPU workers), a self-contained directory with
  explicit imports is a day of work. Untangling flat layers is a quarter.

Every pattern the playbook mandates — repository, service layer, DI, schema-first —
is preserved. Only the *directory grouping* differs.

---

## Multi-tenant isolation — read this before writing any model

Three independent layers. Only the second is a real boundary.

| Layer | Mechanism | Strength |
|---|---|---|
| 1. Application | `WHERE school_id = ...` in queries | Weak — one forgotten filter leaks forever |
| 2. **Database** | **RLS policy on every tenant table** | **Strong — the database refuses** |
| 3. Role | App connects as `sms_app` (`NOBYPASSRLS`, owns nothing) | Required for layer 2 to function |

The chain, end to end:

1. User logs in → JWT is signed with a `sid` (school id) claim.
2. `api/deps.py::get_current_principal` verifies the signature and publishes
   `school_id` into a `ContextVar`.
3. `db/session.py::get_db` reads that ContextVar and issues
   `SELECT set_config('app.current_school_id', <id>, true)`.
4. Every RLS policy compares `school_id` against that setting.

So the tenant boundary is enforced by PostgreSQL on *every statement* — including
raw SQL, ad-hoc ORM queries, and code written by a developer who has never read this
document. That is the point.

**Three failure modes that silently disable all of it:**

- Connecting as `postgres` or as the table owner → superusers and owners bypass RLS.
  Hence the separate `sms_app` role and `FORCE ROW LEVEL SECURITY`.
- Using `SET` instead of `SET LOCAL` / `set_config(..., true)` → the value survives
  past `COMMIT` and leaks onto the next request that reuses the pooled connection.
- A `USING` clause with no `WITH CHECK` → a user can *write* rows into another
  tenant even though they cannot read them back.

`alembic/rls.py` wraps the correct DDL so no migration has to get this right by hand.

**Cross-tenant reads return 404, never 403.** A 403 would confirm the resource
exists, which is itself a cross-tenant information leak.

---

## Directory map

| Path | Responsibility |
|---|---|
| `app/main.py` | Composition root. Builds the app; contains no endpoints. |
| `app/core/config.py` | The only module that reads the environment. Typed, validated at boot. |
| `app/core/context.py` | Request-scoped ambient state (request id, tenant, actor) via ContextVar. |
| `app/core/security.py` | Password hashing + JWT. Pure computation, no I/O. |
| `app/core/exceptions.py` | Domain error hierarchy. Lets services signal failure without importing FastAPI. |
| `app/core/logging.py` | structlog setup; auto-stamps every line with request id + tenant. |
| `app/db/base.py` | `DeclarativeBase` + constraint naming convention. |
| `app/db/mixins.py` | `UUIDPrimaryKeyMixin`, `TimestampMixin`, `SoftDeleteMixin`, `TenantMixin`. |
| `app/db/session.py` | Engine, session factory, **and the RLS tenant binding**. |
| `app/db/registry.py` | Imports every model so Alembic can see it. One line per module. |
| `app/common/repository.py` | Generic async CRUD + pagination/sorting/soft-delete. |
| `app/common/schemas.py` | `Page[T]`, `PageParams`, `SortParams`, RFC 9457 `ProblemDetail`. |
| `app/api/deps.py` | Reusable DI: session, current user, tenant, role guards. |
| `app/api/errors.py` | The **only** place that maps domain errors → HTTP. |
| `app/api/v1/router.py` | Mounts module routers. One line per module. |
| `app/middleware/` | Edge concerns: correlation id, access logging. |
| `app/modules/` | Domain modules — the vertical slices. |
| `alembic/rls.py` | RLS DDL helpers. Autogenerate cannot emit these. |
| `scripts/init-db.sql` | Extensions + the restricted `sms_app` role. |

---

## Conventions

- **Transactions:** `get_db` owns the commit. Services call `flush()` when they need
  a generated id, never `commit()`. One request = one transaction = atomic.
- **Errors:** raise `AppError` subclasses from services. Never `HTTPException`.
- **Responses:** no success envelope (HTTP status already encodes it); `Page[T]` for
  lists; RFC 9457 `application/problem+json` for all errors.
- **Sorting:** client-supplied sort fields are checked against a per-repository
  allowlist. Never interpolate a client string into `ORDER BY`.
- **New model checklist:** add to `db/registry.py` · include `TenantMixin` if
  tenant-owned · call `setup_tenant_table()` in the migration.

---

## Deviations from the bundled FastAPI skill playbook

The playbook's structure is sound; its code samples predate the stack this project
targets. Corrected here:

| Playbook | Used instead | Reason |
|---|---|---|
| `declarative_base()` | `class Base(DeclarativeBase)` | Removed in SQLAlchemy 2.x |
| `sessionmaker(class_=AsyncSession)` | `async_sessionmaker` | Proper async typing |
| `.dict()` | `.model_dump()` | Removed in Pydantic v2 |
| `class Config:` | `model_config = ConfigDict(...)` | Deprecated in Pydantic v2 |
| `datetime.utcnow()` | `datetime.now(UTC)` | Deprecated in 3.12+; returns naive datetimes |
| `python-jose` | `PyJWT` | Unmaintained; algorithm-confusion CVEs |
| `passlib[bcrypt]` | `pwdlib[argon2]` | Passlib breaks on bcrypt ≥ 4.1; Argon2id is current OWASP guidance |
| `AsyncClient(app=app)` | `AsyncClient(transport=ASGITransport(app))` | Removed in httpx 0.28 |
| custom `event_loop` fixture | `asyncio_mode = "auto"` | Removed in pytest-asyncio 1.x |
| `db: AsyncSession` per method | session injected in `__init__` | Session is request state, not a per-call argument |
