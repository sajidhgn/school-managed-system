# Project Structure — Complete Guide

**For a MERN developer moving to Python.**

This document explains every folder and every file in this project: **what** it is,
**where** it lives, and **why** it exists. Wherever a Python concept has a Node/Express
equivalent, the equivalent is given side by side.

Read it top to bottom once. After that, use the **Directory Map** and the
**"How to add a feature"** section as your daily reference.


---

## Table of contents

1. [What this project is, and where it is right now](#1-what-this-project-is-and-where-it-is-right-now)
2. [The mental model: MERN → FastAPI](#2-the-mental-model-mern--fastapi)
3. [Every dependency, and its Node equivalent](#3-every-dependency-and-its-node-equivalent)
4. [The full directory tree](#4-the-full-directory-tree)
5. [File-by-file: what, where, why](#5-file-by-file-what-where-why)
6. [The life of a request (end to end)](#6-the-life-of-a-request-end-to-end)
7. [The four layers, and the one rule that holds them together](#7-the-four-layers-and-the-one-rule-that-holds-them-together)
8. [Multi-tenancy: the thing that makes this project unusual](#8-multi-tenancy-the-thing-that-makes-this-project-unusual)
9. [How to add a new feature, start to finish](#9-how-to-add-a-new-feature-start-to-finish)
10. [Python things that trip up MERN developers](#10-python-things-that-trip-up-mern-developers)
11. [Command cheat sheet](#11-command-cheat-sheet)
12. [What exists vs what is still empty](#12-what-exists-vs-what-is-still-empty)
13. [The product feature checklist](#13-the-product-feature-checklist)

---

## 1. What this project is, and where it is right now

**What:** A multi-tenant SaaS backend for schools. "Multi-tenant" means one running
application and one database serve many schools, and no school can ever see another
school's data.

**Stack:** Python 3.13 · FastAPI · Pydantic v2 · SQLAlchemy 2.x (async) · Alembic ·
PostgreSQL.

**Current state:** a complete, working foundation with **the first two feature modules
delivered end to end**. Think of it as the moment in a MERN project where `app.js`,
`config/`, `middleware/`, `utils/`, error handling, auth helpers and the DB connection
are all done — *and* the first real routes are shipped on top.

Concretely:

- The app boots and serves `/health` **with no database at all** (`DB_ENABLED=false`),
  and against real PostgreSQL when `DB_ENABLED=true`.
- `app/modules/` contains **`tenancy`**, **`auth`**, **`academics`** and **`students`**,
  each a full models → schemas → repository → service → router stack.
- `alembic/versions/` holds **two migrations**: the tenancy/auth bootstrap, and
  classes/sections/students. Every tenant table carries an RLS policy.
- There is **no frontend folder yet**. The config points at a future Next.js app on
  `http://localhost:3000`.

See [§12](#12-what-exists-vs-what-is-still-empty) for the exact state of play, and
[§13](#13-the-product-feature-checklist) for how it maps onto the feature checklist.

---

## 2. The mental model: MERN → FastAPI

The single biggest adjustment is this: **Express is a library you assemble by hand;
FastAPI is a framework that reads your type hints and does work for you.**

In Express you write:

```js
router.post('/students', authMiddleware, validate(studentSchema), async (req, res) => {
  const student = await Student.create(req.body);
  res.status(201).json(student);
});
```

Four separate things there: routing, auth, validation, and the handler. You wired each
one manually, and none of them are connected to your docs.

In FastAPI you write:

```python
@router.post("/students", status_code=201)
async def create_student(
    payload: StudentCreate,       # <- validation. Pydantic parses & validates the body.
    db: DbSession,                # <- dependency injection. Gives you a DB session.
    user: CurrentUser,            # <- auth. Rejects the request if the JWT is bad.
) -> StudentRead:                 # <- response shape. Also documents the endpoint.
    return await StudentService(db).create(payload)
```

The **type annotations are the wiring**. FastAPI reads them at import time and:

- parses + validates the request body against `StudentCreate` (returns 422 if invalid),
- runs the auth dependency behind `CurrentUser` before your function body,
- opens a database session, and closes/commits it after,
- serialises the return value through `StudentRead`,
- generates OpenAPI docs at `/docs` describing all of the above.

You never call `next()`. You never touch `req` or `res` unless you specifically ask for
them. **This is Dependency Injection (DI)**, and it is the core FastAPI idea — the
rough equivalent of Express middleware, but per-parameter, typed, testable, and
auto-documented.

### The concept table

| MERN / Express | Here | Notes |
|---|---|---|
| `app.js` / `server.js` | [main.py](backend/app/main.py) | Composition root — builds the app |
| `express()` | `FastAPI()` | |
| `express.Router()` | `APIRouter()` | |
| Middleware `(req,res,next)` | Middleware **and** Dependencies | Middleware for edge concerns; DI for per-route needs |
| `req.user` set by middleware | `CurrentUser` dependency + ContextVar | Typed, not a magic property bolted onto a request object |
| Mongoose schema | SQLAlchemy model (`models.py`) | Defines the **database table** |
| Joi / Zod schema | Pydantic schema (`schemas.py`) | Defines the **API contract**. Separate on purpose — see §7 |
| `controllers/` | `router.py` | HTTP in, HTTP out. Thin |
| Business logic in the controller | `service.py` | Where it actually belongs |
| `Model.find()` scattered in controllers | `repository.py` | All SQL in one place per domain |
| `process.env.X` anywhere | `app/core/config.py` **only** | One typed, validated place |
| `try/catch` + `res.status(400)` | `raise NotFoundError(...)` | Services raise domain errors; one handler maps them to HTTP |
| `async/await` on Promises | `async/await` on coroutines | Nearly identical syntax, different machinery |
| `package.json` | `pyproject.toml` | |
| `package-lock.json` | `uv.lock` | |
| `node_modules/` | `.venv/` | Per-project, gitignored |
| `npm run <script>` | `make <target>` | See the [Makefile](backend/Makefile) |
| `nodemon` | `uvicorn --reload` | |
| Mongo "just add a field" | **Alembic migration required** | Biggest workflow change. See §10 |

---

## 3. Every dependency, and its Node equivalent

Defined in [pyproject.toml](backend/pyproject.toml).

### Runtime dependencies

| Package | Node equivalent | What it does here |
|---|---|---|
| `fastapi` | `express` | The web framework |
| `uvicorn[standard]` | `node` itself | The ASGI server that runs the app |
| `python-multipart` | `multer` / `body-parser` | Parses form data and file uploads |
| `pydantic` | `zod` / `joi` | Validation + serialisation, driven by type hints |
| `pydantic-settings` | `dotenv` + manual validation | Loads `.env` into a **typed, validated** object |
| `email-validator` | `validator.isEmail` | Powers Pydantic's `EmailStr` type |
| `sqlalchemy[asyncio]` | `mongoose` / `prisma` | The ORM |
| `asyncpg` | `pg` driver | Async PostgreSQL driver |
| `alembic` | `prisma migrate` / `knex migrate` | Schema migrations |
| `pyjwt` | `jsonwebtoken` | Signs and verifies JWTs |
| `pwdlib[argon2]` | `bcrypt` | Password hashing (Argon2id — stronger than bcrypt) |
| `structlog` | `winston` / `pino` | Structured JSON logging |
| `aiosmtplib` | `nodemailer` | Sends email over SMTP, without blocking |
| `jinja2` | `ejs` / `handlebars` | Renders the email HTML templates |

### Dev dependencies

| Package | Node equivalent | What it does |
|---|---|---|
| `pytest` | `jest` / `mocha` | Test runner |
| `pytest-asyncio` | (built into jest) | Lets tests be `async def` |
| `pytest-cov` | `nyc` / `--coverage` | Coverage reports |
| `httpx` | `supertest` / `axios` | Test client — calls the app **in-process**, no network |
| `ruff` | `eslint` + `prettier` **combined** | Linting **and** formatting, one very fast tool |
| `mypy` | `tsc --noEmit` | Static type checking. Configured in `strict` mode |
| `aiosqlite` | `mongodb-memory-server` | In-memory DB for fast unit tests |

**Note on two deliberate choices** (documented in [security.py](backend/app/core/security.py)):
`PyJWT` is used instead of the more commonly-blogged `python-jose` (unmaintained,
algorithm-confusion CVEs), and `pwdlib[argon2]` instead of `passlib[bcrypt]` (passlib
crashes against bcrypt ≥ 4.1). If you follow an older FastAPI tutorial, it will tell you
to use the broken ones.

---

## 4. The full directory tree

```
School Management System/
├── PROJECT_STRUCTURE.md          ← you are here
├── .claude/                      ← AI tooling config. Not part of the app.
└── backend/                      ← the entire Python application
    │
    ├── pyproject.toml            ← package.json: deps + tool config (ruff, mypy, pytest)
    ├── uv.lock                   ← package-lock.json: exact resolved versions
    ├── Makefile                  ← npm scripts: `make dev`, `make test`, `make check`
    ├── README.md                 ← architecture rationale (read it, it's good)
    ├── .env                      ← YOUR secrets. Gitignored. Never commit.
    ├── .env.example              ← the template. Committed. Every var documented.
    ├── .gitignore
    ├── alembic.ini               ← migration tool config
    ├── docker-compose.yml        ← local PostgreSQL + API stack
    │
    ├── .venv/                    ← node_modules equivalent. Gitignored.
    ├── .ruff_cache/  .mypy_cache/  .pytest_cache/   ← tool caches. Gitignored.
    │
    ├── app/                      ← ★ ALL APPLICATION CODE
    │   ├── __init__.py           ← marks `app` as a Python package (see §10)
    │   ├── main.py               ← ★ entry point. Builds & wires the whole app.
    │   │
    │   ├── core/                 ← foundations. No HTTP, no SQL. Pure logic.
    │   │   ├── config.py         ← the ONLY place that reads env vars
    │   │   ├── context.py        ← per-request ambient state (request id, tenant)
    │   │   ├── security.py       ← password hashing + JWT create/verify
    │   │   ├── otp.py            ← one-time-password generation & verification
    │   │   ├── exceptions.py     ← domain error classes (NotFoundError, etc.)
    │   │   └── logging.py        ← structlog setup
    │   │
    │   ├── db/                   ← database plumbing. No business logic.
    │   │   ├── base.py           ← the SQLAlchemy `Base` every model inherits
    │   │   ├── mixins.py         ← reusable column sets (uuid pk, timestamps, tenant)
    │   │   ├── session.py        ← ★ engine, session factory, RLS tenant binding
    │   │   └── registry.py       ← imports every model so Alembic can see them
    │   │
    │   ├── common/               ← generic building blocks shared by all modules
    │   │   ├── repository.py     ← ★ generic async CRUD base class
    │   │   ├── schemas.py        ← Page[T], PageParams, SortParams, ProblemDetail
    │   │   └── email/
    │   │       ├── sender.py     ← SMTP + console transports
    │   │       ├── templates.py  ← Jinja2 rendering
    │   │       └── templates/
    │   │           ├── otp.html
    │   │           └── otp.txt
    │   │
    │   ├── api/                  ← the HTTP edge
    │   │   ├── deps.py           ← ★ reusable dependencies (auth, db, pagination)
    │   │   ├── errors.py         ← ★ the ONLY place domain errors → HTTP responses
    │   │   └── v1/
    │   │       ├── router.py     ← mounts every module's router
    │   │       └── routes/
    │   │           └── health.py ← /health and /health/ready
    │   │
    │   ├── middleware/
    │   │   └── request_context.py ← request id + access logging
    │   │
    │   └── modules/              ← ★ ALL BUSINESS FEATURES LIVE HERE
    │       ├── tenancy/          ← schools: registration, approval, suspension
    │       ├── auth/             ← register, verify, login, 2FA, refresh, reset
    │       ├── academics/        ← classes (grades) + sections
    │       └── students/         ← SIS directory + public admissions
    │                                 (attendance/, timetable/, fees/, ... to come)
    │
    ├── alembic/                  ← database migrations
    │   ├── env.py                ← migration runtime config
    │   ├── rls.py                ← Row-Level Security DDL helpers
    │   ├── script.py.mako        ← template for generated migration files
    │   └── versions/
    │       ├── ..._bootstrap_tenancy_and_auth.py
    │       └── ..._add_classes_sections_and_students.py
    │
    ├── tests/
    │   ├── conftest.py           ← shared fixtures (auto-discovered by pytest)
    │   ├── unit/                 ← no I/O. Fast.
    │   │   ├── test_otp.py
    │   │   └── test_email.py
    │   └── integration/          ← full HTTP requests through the real app
    │       ├── conftest.py       ← DB fixtures; app connects as `sms_app`
    │       ├── test_health.py
    │       ├── test_rls.py       ← cross-tenant isolation proofs
    │       ├── test_tenancy.py
    │       ├── test_auth_flows.py
    │       ├── test_academics.py
    │       └── test_students.py
    │
    ├── scripts/
    │   ├── init-db.sql           ← creates extensions + the restricted `sms_app` role
    │   ├── create_super_admin.py ← seed the first platform operator
    │   └── smoke_auth.sh         ← end-to-end auth check against a running server
    │
    └── docker/
        └── Dockerfile            ← multi-stage production image
```

`★` marks the files you will read and edit most often.

---

## 5. File-by-file: what, where, why

Every source file in this project opens with a docstring explaining its own purpose.
That is deliberate — open the file and the "why" is right there. This section is the
index.

### 5.1 Root config files

#### [pyproject.toml](backend/pyproject.toml) — *your `package.json`*

One file, four jobs:

- `[project] dependencies` — runtime packages (like `dependencies` in package.json)
- `[dependency-groups] dev` — dev packages (like `devDependencies`)
- `[tool.ruff]` — linter + formatter rules (your `.eslintrc` + `.prettierrc`)
- `[tool.mypy]` — type checker rules (your `tsconfig.json`)
- `[tool.pytest.ini_options]` — test runner config (your `jest.config.js`)

Node scatters these across five dotfiles; Python standardised on one. Two settings worth
knowing:

- `strict = true` under `[tool.mypy]` — full type checking, like `"strict": true` in tsconfig.
- `asyncio_mode = "auto"` — you can write `async def test_x()` without decorating each test.

#### [uv.lock](backend/uv.lock) — *your `package-lock.json`*

Exact resolved versions of every transitive dependency. **Commit it.** Never edit it by
hand. `uv` is the package manager — a very fast Rust-based replacement for `pip`, made by
the same team as `ruff`.

#### [Makefile](backend/Makefile) — *your `npm scripts`*

Python has no `"scripts"` field, so a Makefile fills the gap. Run `make help` to list
everything. Key targets: `make dev`, `make test`, `make check`, `make migration`,
`make migrate`.

Why it matters: CI runs the exact same `make check` you run locally, so "passes on my
machine" and "passes in CI" mean the same thing.

#### [.env](backend/.env) / [.env.example](backend/.env.example)

`.env` holds your real secrets and is gitignored. `.env.example` is the committed
template. **Every variable in `.env.example` maps 1:1 to a field on the `Settings` class
in `config.py`** — that mapping is the contract. If you add a setting, add it in both places.

#### [alembic.ini](backend/alembic.ini)

Migration tool config. Note that `sqlalchemy.url` is deliberately **blank** — the
connection string is injected at runtime from `config.py`, so credentials never end up in
a committed file.

#### [docker-compose.yml](backend/docker-compose.yml)

Spins up PostgreSQL 18 (on host port **5433**, to avoid clashing with a local PostgreSQL
on 5432) plus the API. Runs `scripts/init-db.sql` automatically on first boot. Optional —
if you already have PostgreSQL locally, just point `.env` at it.

---

### 5.2 `app/main.py` — the composition root

**What:** builds and configures the `FastAPI` instance.
**Why it exists:** every app needs one place where settings, logging, middleware,
routers, error handlers and the database are wired together. That is the *Composition
Root* pattern — dependencies are assembled here and nowhere else.

**It contains no endpoints.** If you find yourself adding a route here, it belongs in a
module router instead.

Three things to understand:

**1. `create_app()` is a factory, not a module-level `app = FastAPI()`.**
A factory lets tests build a fresh, independently-configured app per test with no
import-time side effects. The `app = create_app()` line at the bottom exists only
because `uvicorn app.main:app` needs an importable attribute.

**2. `lifespan` replaces `@app.on_event("startup")`.**
Startup and shutdown live in a single context manager, so setup and its matching
teardown sit adjacent in the code — you cannot add a resource and forget to release it.
The DB connection pool is created here, not at import time, so importing `app.main`
never opens a socket.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings)
    if settings.DB_ENABLED:
        init_engine(settings)
    yield                          # ← the app serves requests here
    await dispose_engine()         # ← shutdown
```

**3. Middleware order is reversed and this is load-bearing.**
Starlette applies middleware in **reverse** registration order — the **last** one added
is the **outermost** wrapper. The code adds `RequestContext` → `GZip` → `CORS` →
`TrustedHost`, producing the chain:

```
TrustedHost → CORS → GZip → RequestContext → your route
```

`RequestContext` is innermost so its timing measurement covers route execution rather
than compression.

---

### 5.3 `app/core/` — foundations

Pure logic. Nothing in here imports `fastapi` (except nothing does), touches HTTP, or
runs SQL. That is what makes it all trivially unit-testable.

#### [config.py](backend/app/core/config.py)

**The only module in the codebase allowed to read the environment.** Nothing else may
call `os.getenv`. That keeps configuration typed, validated at startup, and discoverable
in one place.

`Settings` is a `pydantic_settings.BaseSettings` subclass — declare a field with a type
and Pydantic reads it from `.env`, coerces it, and validates it **at boot**. A missing or
malformed value crashes the app at startup rather than at 3am on the first request that
touches it.

```python
class Settings(BaseSettings):
    APP_NAME: str = "School Management System"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30      # "30" from .env becomes int 30
    CORS_ORIGINS: list[str] = Field(default_factory=list)   # parses JSON from .env
```

Two custom validators refuse to boot production with an insecure config:

- `EMAIL_BACKEND=console` in production → **crash**. The console backend writes OTP codes
  to the log in plaintext and sends no actual mail, so it would be both a credential leak
  and a total outage of signup/reset/2FA.
- A default `SECRET_KEY` in production/staging → **crash**. A weak signing key means
  anyone can forge a JWT, and the JWT carries the `school_id` claim, which *is* the tenant
  boundary.

`get_settings()` is wrapped in `@lru_cache` — it is a singleton, but exposed as a
*function* so tests can override it via FastAPI's `dependency_overrides`.

#### [context.py](backend/app/core/context.py)

**The problem it solves:** three facts are needed almost everywhere but belong in no
function signature — the request id (for log correlation), the current school (needed by
every query), and the acting user (for audit columns). Threading them through
router → service → repository → model as explicit arguments would pollute every signature
in the codebase.

**The solution:** `ContextVar`. This is Python's async-safe equivalent of Node's
`AsyncLocalStorage`. Each asyncio task gets its own copy, so **two concurrent requests
can never see each other's tenant**.

```python
_school_id: ContextVar[UUID | None] = ContextVar("school_id", default=None)
```

Who writes to it, who reads it:

| | |
|---|---|
| `middleware/request_context.py` | **writes** `request_id` at the edge |
| `api/deps.py` | **writes** `school_id` / `user_id` after verifying the JWT |
| `db/session.py` | **reads** `school_id` → issues `SET LOCAL app.current_school_id` |
| `core/logging.py` | **reads** `request_id` → stamps every log line |

This ContextVar is the link in the chain that makes tenant isolation work. See §8.

#### [security.py](backend/app/core/security.py)

Four functions, nothing else: `hash_password`, `verify_password`, `create_access_token`,
`decode_token`. Pure computation — it knows nothing about users, sessions or the
database. That is the auth service's job.

The important part is what goes into an access token:

```python
{
  "sub": "<user uuid>",   # RFC 7519 requires this to be a string
  "typ": "access",        # checked on decode → a refresh token can never be replayed
  "sid": "<school uuid>", # ★ THE TENANT BOUNDARY
  "role": "teacher",
  "sa": false,            # super admin
  "iat": ..., "exp": ..., "jti": "<uuid>"   # jti enables future revocation
}
```

The **refresh** token deliberately carries **no** tenant or role claims — those are
re-read from the database on refresh, so a revoked user or changed role takes effect
within one access-token lifetime (30 min) rather than one refresh-token lifetime (7 days).

`decode_token` passes `algorithms=[...]` as an allowlist, which blocks the classic
`alg: none` forgery attack.

#### [otp.py](backend/app/core/otp.py)

Generates and verifies the 6-digit codes used for signup verification, password reset and
login 2FA. Read the module docstring — it explains four decisions in detail:

1. **`secrets`, never `random`.** `random` is a Mersenne Twister seeded from the clock;
   observing a few outputs lets an attacker predict all subsequent codes.
2. **HMAC-SHA256 with a server-side pepper, not Argon2 and not a bare hash.** A 6-digit
   code has only 10⁶ possibilities — a plain SHA-256 of it is brute-forced from a database
   dump in under a second. HMAC keyed with `SECRET_KEY` (which the database does not
   contain) makes a dump useless, and verifies in microseconds.
3. **The purpose is bound into the digest.** The hash covers `purpose|identifier|code`.
   Without this, a code mailed for "verify your email" could be replayed against the
   password-reset endpoint.
4. **`hmac.compare_digest`, not `==`.** `==` short-circuits at the first differing byte,
   leaking the digest one byte at a time through timing.

It deliberately does **not** handle expiry, attempt-counting or single-use enforcement —
those are *state*, and state lives in the database, owned by the future auth service.

#### [exceptions.py](backend/app/core/exceptions.py)

The domain error hierarchy. **This is one of the most important patterns to internalise.**

In Express you probably did `res.status(404).json({ error: 'not found' })` inside a
service function. That couples the service to HTTP — the moment you want to call it from
a CLI script, a background worker, or a test, it breaks.

Here, services raise a domain error and know nothing about HTTP:

```python
raise NotFoundError("Student not found.")
```

| Class | Status | Code |
|---|---|---|
| `ValidationError` | 422 | `VALIDATION_ERROR` |
| `NotFoundError` | 404 | `NOT_FOUND` |
| `ConflictError` | 409 | `CONFLICT` |
| `AuthenticationError` | 401 | `UNAUTHENTICATED` |
| `AuthorizationError` | 403 | `FORBIDDEN` |
| `RateLimitError` | 429 | `RATE_LIMITED` |
| `ExternalServiceError` | 502 | `EXTERNAL_SERVICE_ERROR` |
| `ServiceUnavailableError` | 503 | `SERVICE_UNAVAILABLE` |

A single handler in `api/errors.py` — the *only* file that knows about both vocabularies —
translates them into HTTP responses.

**Rule: never raise `HTTPException` from a service.** Only routers and dependencies may
do that, and even then, prefer an `AppError`.

#### [logging.py](backend/app/core/logging.py)

`structlog` config. Two things it buys you over `print`:

- **Every log line is automatically stamped** with `request_id`, `school_id` and
  `user_id`, pulled from the ContextVar by a processor. You never pass them manually.
  In a multi-tenant incident the first question is always "which school, which request?"
- **Console renderer locally, JSON in production** — one switch, `LOG_JSON`. JSON output
  is ingestible by CloudWatch / Loki / Datadog.

Usage everywhere: `logger = get_logger(__name__)` at module scope, then
`logger.info("student_created", student_id=str(sid))` — event name first, then keyword
fields. Not f-strings.

---

### 5.4 `app/db/` — database plumbing

#### [base.py](backend/app/db/base.py)

Defines `Base`, the declarative base every model inherits from. Two features:

**A naming convention for constraints.** Without it PostgreSQL invents names like
`students_school_id_fkey1`, which differ between environments — so Alembic cannot
reliably `DROP` them and your downgrade migrations break. **Do not change this convention
after the first migration ships.**

**Automatic table names.** `class StudentEnrollment(Base)` → table
`student_enrollments`. Convention over configuration; a model can still override
`__tablename__` for irregular plurals.

#### [mixins.py](backend/app/db/mixins.py)

Roughly forty tables will need the same four things. Mixins give one definition and forty
consistent usages. You compose them:

```python
class Student(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    name: Mapped[str] = mapped_column(String(120))
```

| Mixin | Adds | Why |
|---|---|---|
| `UUIDPrimaryKeyMixin` | `id: UUID` | Sequential integers are enumerable — `GET /students/1..N` from a rival school is a real attack. UUIDs also let ids be generated before insert (idempotent retries, offline clients) |
| `TimestampMixin` | `created_at`, `updated_at` | Uses the **database** clock (`server_default=func.now()`), not the app clock — multiple app instances drift |
| `SoftDeleteMixin` | `deleted_at` | Deleting a student must not destroy their fee history, attendance record or certificates — those are financial and legal records |
| `TenantMixin` | `school_id` FK | ★ Required on **every** tenant-owned table. `nullable=False` (an orphan row is invisible to RLS and becomes a permanent leak), `ondelete="CASCADE"` (GDPR-style deletion), and indexed (RLS adds an implicit `WHERE school_id = ...` to *every* query) |

Note: `SoftDeleteMixin` means every query must filter `deleted_at IS NULL`.
`BaseRepository` applies that automatically so call sites cannot forget.

#### [session.py](backend/app/db/session.py) ★

The most important file in `db/`. Owns three things:

**1. The engine** (one per process — like a Mongo connection pool). Built **lazily** by
`init_engine()` during startup, not at import time, which is what lets the test suite and
the DB-less phase of development import the app freely.

Pool settings worth knowing: `pool_pre_ping=True` verifies a pooled connection is alive
before handing it out (without it, connections killed by a proxy surface as random 500s),
and `pool_recycle=1800` stays below typical cloud idle timeouts.

**2. The `get_db` dependency** — this is your unit of work:

```python
async def get_db():
    async with factory() as session:
        await _apply_tenant_guc(session, get_school_id(), is_super_admin())
        try:
            yield session
            await session.commit()      # commit on success
        except Exception:
            await session.rollback()    # rollback on ANY exception
            raise
```

**One request = one transaction = atomic.** A service that writes to three tables gets
atomicity for free.

> **★ The rule you must remember: services never call `session.commit()`.**
> They call `session.flush()` when they need a generated id before the request ends.
> `get_db` owns the commit.

**3. The RLS tenant binding** — `_apply_tenant_guc` copies the tenant from the verified
JWT into a PostgreSQL session variable. This is the bridge that makes the whole isolation
mechanism work. See §8.

**4. `session_scope()`** — a context manager for code running **outside** a request
(background jobs, seed scripts, CLI commands). No HTTP request means no ambient context,
so the tenant must be passed explicitly:

```python
async with session_scope(school_id) as session:
    await StudentRepository(session).list()
```

#### [registry.py](backend/app/db/registry.py)

**Small file, catastrophic failure mode if ignored.**

SQLAlchemy only knows about a model once its module has been imported. Alembic's
autogenerate compares `Base.metadata` against the live database — so a model that was
never imported is *absent* from the metadata, and autogenerate will read its existing
table as "not in the model" and generate a **`DROP TABLE`**.

This file makes the import explicit and reviewable. Today it is all commented out:

```python
# from app.modules.students import models as student_models
```

> **★ Rule: every new `app/modules/<name>/models.py` MUST be added here, in the same
> commit that creates it.**

---

### 5.5 `app/common/` — shared building blocks

#### [repository.py](backend/app/common/repository.py) ★

A generic async CRUD base class. About 80% of data access in a CRUD-heavy system is the
same six operations against different tables.

```python
class StudentRepository(BaseRepository[Student]):
    model = Student
    sortable_fields = frozenset({"name", "admission_number", "created_at"})

    async def get_by_admission_number(self, num: str) -> Student | None:
        return await self.find_one(Student.admission_number == num)
```

You get for free: `get`, `find_one`, `exists`, `count`, `list` (paginated), `create`,
`update`, `soft_delete`, `hard_delete`.

Details worth knowing:

- **`sortable_fields` is an allowlist, and it is empty by default.** `sort_by` arrives as
  a raw string from the client; `apply_sort` rejects anything not on the list. Never
  interpolate a client string into `ORDER BY`.
- **Sorting always appends `, id`** as a tiebreaker. Unstable ordering is a classic
  pagination bug — rows shuffle between pages and users see duplicates.
- **`_base_select` deliberately does NOT filter `school_id`.** Tenant scoping is enforced
  by PostgreSQL RLS at the connection level. Adding it here too would mean a missing
  filter is survivable — which is exactly the complacency RLS is meant to remove.
- **`create` calls `flush()` then `refresh()`, not `commit()`.** See the rule above.
- **`list` returns `(rows, total)`, not a `Page`.** The repository must not depend on
  API-layer schemas; the *service* assembles the `Page`. Dependency arrow points inward.
- **`update` expects `model_dump(exclude_unset=True)`** so "field omitted" and "field
  explicitly set to null" stay distinguishable — the difference between PATCH semantics
  and accidental data loss.

#### [schemas.py](backend/app/common/schemas.py)

Cross-cutting Pydantic contracts:

- **`BaseSchema`** — base for every schema in the project. `from_attributes=True` lets you
  build a schema straight from an ORM object: `StudentRead.model_validate(student_orm)`.
  `str_strip_whitespace=True` turns `" Ahmed "` into `"Ahmed"`.
- **`PageParams`** — `?page=1&size=20`, used as a dependency. Offset pagination (not
  cursor) because admin tables need "jump to page 7" and a total count.
- **`SortParams`** — `?sort_by=name&sort_dir=asc`.
- **`Page[T]`** — the response shape of every list endpoint. FastAPI renders each
  parameterisation as its own OpenAPI schema, so your frontend gets a precise
  `PageStudentRead` TypeScript type instead of `Page<any>`.
- **`ProblemDetail`** — the RFC 9457 error body (see below).

**Design decision worth flagging:** there is **no success envelope**. No
`{"success": true, "data": {...}}`. HTTP already encodes success in the status code, and
an envelope makes generated client types markedly worse. Errors *do* get a structured
body, because HTTP does not standardise one.

#### [email/sender.py](backend/app/common/email/sender.py)

`EmailSender` is a `Protocol` — Python's structural typing, closest to a TypeScript
`interface`. Any object with a matching `async def send(self, message)` satisfies it, so
a test fake needs no import and no inheritance.

Two backends:

- **`ConsoleEmailSender`** — logs the message, sends nothing. **This is the default.** A
  misconfigured test run that emails real parents is unrecoverable; the failure mode of
  this default is "no email sent", which is always recoverable.
- **`SmtpEmailSender`** — real delivery via `aiosmtplib`. Not stdlib `smtplib`, because
  that is **blocking**: one slow send would stall the entire event loop and freeze every
  concurrent request in the process.

Two SMTP details that bite people: every message is `multipart/alternative` (HTML **and**
plaintext — an OTP that renders as raw HTML tags in a text-only client is unreadable, and
Gmail penalises HTML-only mail), and `use_tls` (implicit TLS, port 465) vs `start_tls`
(STARTTLS upgrade, port 587) are **mutually exclusive**. Setting both raises; setting
neither sends credentials in the clear. Nodemailer's `secure: true` is `SMTP_USE_TLS`.

**Sending is never awaited on the request path** — SMTP handshake + TLS against Gmail is
commonly 500ms–3s. The auth service will dispatch sends via FastAPI's `BackgroundTasks`.

#### [email/templates.py](backend/app/common/email/templates.py) + `templates/`

Jinja2 rendering. `autoescape` is **on** — template context includes user-controlled
values like a school's name, and a school named `<script>alert(1)</script>` must not
become executable markup. Jinja2's default is off, which is the wrong default for HTML.

`StrictUndefined` turns a typo'd variable into a loud render-time error instead of
silently producing "Your code is:" with no code.

---

### 5.6 `app/api/` — the HTTP edge

#### [deps.py](backend/app/api/deps.py) ★

The dependency library. **Read this file properly** — it is where the FastAPI DI model
clicks.

The style used throughout is `Annotated` aliases:

```python
DbSession = Annotated[AsyncSession, Depends(get_tenant_db)]
CurrentUser = Annotated[Principal, Depends(get_current_principal)]

# then in a route, this reads like plain typed Python:
async def list_students(db: DbSession, user: CurrentUser) -> Page[StudentRead]: ...
```

What is available:

| Alias | Gives you | Notes |
|---|---|---|
| `SettingsDep` | `Settings` | Overridable in tests |
| `CurrentUser` | `Principal` | Decoded JWT. **Zero DB queries** — everything needed is in the signed token |
| `CurrentSchool` | `UUID` | Requires a tenant-scoped caller; 403 otherwise |
| `SuperAdmin` | `Principal` | Platform-level routes only |
| `DbSession` | `AsyncSession` | **Authenticated + tenant-bound.** Use this by default |
| `PublicDbSession` | `AsyncSession` | Unauthenticated (login, public admissions form). No tenant → RLS tables return zero rows |
| `Pagination` | `PageParams` | |
| `Sorting` | `SortParams` | |
| `SearchQuery` | `str \| None` | |
| `require_roles("admin")` | dependency | Use in `dependencies=[Depends(...)]` |

**Two subtleties that are easy to break:**

**1. `get_current_principal` has a deliberate side effect.** It writes `school_id` into
the ContextVar. That side effect *is* the tenant isolation mechanism — `get_db` reads it
moments later.

**2. `get_tenant_db` has an "unused" parameter that is not decoration:**

```python
async def get_tenant_db(
    _principal: CurrentUser,                      # ← forces auth to resolve FIRST
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncSession:
    return session
```

FastAPI resolves the dependency graph depth-first. Without `_principal`, `get_db` could
run *before* the JWT was decoded, producing a session with **no tenant bound**. Removing
that parameter would silently disable tenant isolation. Leave it.

#### [errors.py](backend/app/api/errors.py) ★

The **only** module allowed to know both the domain vocabulary (`AppError`) and the HTTP
vocabulary. That is what lets services stay transport-agnostic.

Every error — from any source — comes out as **RFC 9457 Problem Details**, with content
type `application/problem+json`:

```json
{
  "type": "https://docs.example.com/errors/not-found",
  "title": "NotFound",
  "status": 404,
  "detail": "Student not found.",
  "instance": "3fa85f64-...",     // the request id — quotable in a support ticket
  "code": "NOT_FOUND"             // stable machine code the frontend branches on
}
```

Handlers registered, most to least specific:

| Exception | → | Behaviour |
|---|---|---|
| `AppError` | its own status | Message returned **verbatim** (it was written for the client) |
| `RequestValidationError` | 422 | Pydantic's `loc` tuple flattened to a dotted field path that maps onto a form field |
| `StarletteHTTPException` | as-is | Catches framework 404s/405s so they match the same shape |
| `IntegrityError` | 409 | Safety net for the race where two requests both pass a uniqueness pre-check |
| `SQLAlchemyError` | 503 | |
| `Exception` | 500 | **Generic message only.** Full traceback logged server-side |

**The security rule encoded here:** expected errors return their message; unexpected ones
return a fixed string. An unhandled `IntegrityError` echoed to the client would disclose
table names, column names and constraint definitions.

#### [v1/router.py](backend/app/api/v1/router.py)

Composition only — no handlers. Every module's router gets mounted here in one line, so
`main.py` never needs editing when a module is added. The commented-out lines are the
delivery roadmap, and their order controls section ordering in the Swagger docs.

**Why version the API:** the frontend and any mobile apps deploy independently of this
backend. A URL version segment lets you ship a breaking change as `/api/v2` while
`/api/v1` keeps serving existing clients.

#### [v1/routes/health.py](backend/app/api/v1/routes/health.py)

Mounted **outside** the version prefix (`/health`, not `/api/v1/health`) because an
orchestrator's probe URL must not break when the API moves to v2.

The liveness/readiness distinction is operationally important:

- **`/health` (liveness)** — "is this process alive?" Never touches the database. If it
  fails, the orchestrator **restarts** the container.
- **`/health/ready` (readiness)** — "can this process serve traffic?" Runs `SELECT 1`. If
  it fails, the orchestrator stops **routing** to it but does not restart it.

Conflating them means a brief database blip triggers a restart storm across every
instance simultaneously — turning a short outage into a total one.

---

### 5.7 `app/middleware/request_context.py`

Two things must happen at the very edge of every request, before any route code runs:
assign a correlation id, and start the access-log timer. Middleware is the right place
because it wraps *every* request, including ones that never reach a route (404s,
validation failures).

- Honours an inbound `X-Request-ID` if a gateway or the frontend already set one — that
  is what makes a trace span multiple services.
- Publishes it into the ContextVar so logs and error bodies pick it up.
- Emits one structured access-log line per request with its duration.
- Adds `Server-Timing: app;dur=12.3` to the response, so browser devtools chart backend
  latency alongside network time.
- **Always resets the ContextVar in `finally`** — asyncio tasks are reused, and a stale
  id would mislabel a later log line.

---

### 5.8 `app/modules/` — where your features go ★

This is the most important directory in the project.

The common FastAPI tutorial layout groups by *technical layer*: one `models/` directory,
one `services/` directory, one `routers/` directory. That works up to roughly ten tables.
This system has eight domains heading toward forty-plus tables, so it groups by **domain**
instead, with the layers *inside* each module — a **modular monolith**:

```
app/modules/students/
├── __init__.py
├── models.py       SQLAlchemy tables + constraints
├── schemas.py      Pydantic request/response contracts
├── repository.py   data access (SQL only)
├── service.py      business rules
└── router.py       HTTP endpoints
```

Why this scales better here:

- **Change locality.** "Add a guardian phone number" touches five files in **one**
  directory, not five files scattered across five directories.
- **Reviewable boundaries.** An import of `modules.finance` from inside `modules.students`
  is visible in a diff and can be challenged. With flat layers, cross-domain coupling is
  invisible.
- **Extraction path.** If one module ever needs to become its own service, a
  self-contained directory with explicit imports is a day of work. Untangling flat layers
  is a quarter.

Delivered so far: `tenancy`, `auth`, `academics` (classes + sections), `students`.
Still to come (see the roadmap comments in `router.py` and `registry.py`): `attendance`,
`timetable`, `fees`, `communications`, `documents`, `search`, `inventory`, `ai`.

**Why classes and sections live in `academics/`, not `classes/`:** `class` is a Python
keyword, so the package would be awkward to import and the model has to be
`SchoolClass` regardless. Grouping the grade/section hierarchy under `academics`
also leaves the obvious home for the timetable and attendance modules that read it.
The HTTP prefix is still `/api/v1/classes` — the URL follows the domain language,
not the Python package name.

If you have done Nest.js, this is exactly its module concept. If you have only done
Express, it is `routes/students.js` + `models/Student.js` + `services/studentService.js`
collapsed into one folder.

---

### 5.9 `alembic/` — migrations

This is the biggest workflow change from MongoDB. **You cannot just add a field.** The
database has a fixed schema, and changing it requires a versioned, reviewable, reversible
migration file.

Think `prisma migrate` or `knex migrate`, but with autogeneration: Alembic **diffs your
Python models against the live database** and writes the migration for you.

#### [env.py](backend/alembic/env.py)

Supplies Alembic with two things from the application itself, so there is one definition
of each and they cannot drift: the DSN (from `config.py`) and the target schema
(`Base.metadata`).

Configured with `compare_type=True` and `compare_server_default=True` — both off by
default in Alembic, and both off means silent schema drift.

**★ Critical operational note documented in this file:** Alembic connects as the table
**owner** (needs DDL rights, and implicitly bypasses RLS). The application connects as
`sms_app`, which has DML rights only and no `BYPASSRLS`. Using one role for both would
silently disable every RLS policy.

#### [rls.py](backend/alembic/rls.py) ★

Alembic's autogenerate understands tables, columns, indexes and constraints. It does
**not** understand Row-Level Security — it will never emit `ENABLE ROW LEVEL SECURITY` or
`CREATE POLICY`. Left to hand-written SQL, sooner or later a table ships with a
`school_id` column but no policy, and that table silently leaks every school's data to
every other school.

These helpers make the correct thing a one-liner:

```python
from alembic.rls import setup_tenant_table

def upgrade():
    op.create_table("students", ...)
    setup_tenant_table("students")     # ← grant + enable RLS + install the policy
```

The generated policy has both `USING` (filters which rows are **visible**) and
`WITH CHECK` (validates rows being **written**). Both are required — a `USING`-only policy
would let School A insert a row stamped with School B's id.

#### `versions/` — **empty**

Generated migrations land here, named
`2026_07_19_1430-a1b2c3d4e5f6_add_students_table.py`. Timestamped so chronological sort
order makes the history readable, which bare hashes do not. **Commit them. Never edit one
after it has been applied anywhere.**

---

### 5.10 `tests/`

pytest, not jest, but the shape is familiar.

#### [conftest.py](backend/tests/conftest.py)

Shared fixtures. **`conftest.py` is auto-discovered by pytest** — fixtures defined here
are available in every test file with no imports. Roughly your `jest.setup.js`, but the
fixtures are injected by parameter name:

```python
async def test_health(client: AsyncClient):    # ← `client` fixture injected by name
    response = await client.get("/health")
```

Three fixtures: `settings` (built explicitly with `_env_file=None` so tests never read
your local `.env`), `app` (a fresh app **per test**, so a dependency override in one test
cannot affect another), and `client` (an `httpx.AsyncClient` wired straight to the ASGI
app — **no network, no port binding**, but the real middleware and exception-handler
stack).

`unit/` = no I/O, fast (`test_otp.py`, `test_email.py`). `integration/` = full HTTP
requests through the real app (`test_health.py`).

---

### 5.11 `scripts/init-db.sql`

Run once per database, as a superuser. Two jobs:

**Extensions:** `pgcrypto` (server-side UUID defaults), `pg_trgm` (trigram indexes — the
global-search omnibar needs these, or `ILIKE '%ahmed%'` degrades to a full table scan on
every keystroke), `unaccent` ("Zoë" matches "Zoe").

**The `sms_app` role.** This is the one that matters. PostgreSQL grants two silent RLS
exemptions: superusers bypass it entirely, and table **owners** bypass it unless the table
is set to `FORCE`. So an app connecting as `postgres` has every policy silently disabled.
`sms_app` is `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOBYPASSRLS`, owns nothing, and
cannot create anything. It can only ever run DML.

Runs automatically on first boot of the docker-compose `db` service. For a local
PostgreSQL, run it by hand:
`psql -U postgres -d school_manage_db -f scripts/init-db.sql`

### 5.12 `docker/Dockerfile`

Multi-stage build. The builder stage carries `uv`, build toolchains and caches — none of
which belong in the running image (every extra binary is attack surface). Only the
virtualenv and application code are copied forward: roughly 1.2GB → 250MB.

Dependency files are copied **first, alone**, so Docker's layer cache makes a code-only
rebuild take seconds instead of minutes. Runs as unprivileged `appuser`. No `--reload`
and no `--workers` — process count is the orchestrator's job.

---

## 6. The life of a request (end to end)

Trace `GET /api/v1/students?page=2` through the whole system:

```
1.  uvicorn receives the HTTP request
        │
2.  TrustedHostMiddleware   — production only: is the Host header legitimate?
        │
3.  CORSMiddleware          — is this Origin allowed?
        │
4.  GZipMiddleware          — will compress the response on the way back out
        │
5.  RequestContextMiddleware
        ├─ generates or reuses X-Request-ID
        ├─ set_request_id(...)  →  ContextVar
        └─ starts the timer
        │
6.  FastAPI matches the route, then resolves its dependencies (depth-first):
        │
        ├─ CurrentUser → get_current_principal()
        │      ├─ reads the Authorization: Bearer header
        │      ├─ decode_token()  — verifies signature + expiry + typ claim
        │      └─ ★ set_school_id(...) → ContextVar
        │
        ├─ DbSession → get_tenant_db() → get_db()
        │      ├─ opens an AsyncSession (a transaction begins)
        │      └─ ★ SELECT set_config('app.current_school_id', '<uuid>', true)
        │
        └─ Pagination → PageParams(page=2, size=20)
        │
7.  The route handler runs — thin. Delegates immediately:
        return await StudentService(db).list_students(params)
        │
8.  Service — business rules. Checks permissions, orchestrates. No SQL, no HTTP.
        │
9.  Repository — builds and executes the SELECT.
        │
10. PostgreSQL evaluates the RLS policy on `students`:
        WHERE school_id = current_setting('app.current_school_id')::uuid
    ★ Rows belonging to other schools do not exist as far as this query is concerned.
        │
11. Service wraps the rows in Page[StudentRead]
        │
12. FastAPI serialises via the response_model
        │
13. get_db commits the transaction and closes the session
        │
14. RequestContextMiddleware adds X-Request-ID + Server-Timing, logs the access line
        │
15. GZip compresses, CORS adds headers, response goes out
```

**If anything raises at any point in steps 7–11:** `get_db` rolls back the transaction and
re-raises → `api/errors.py` catches it → renders an RFC 9457 Problem Details body carrying
the request id → `RequestContextMiddleware` still logs the failed request.

---

## 7. The four layers, and the one rule that holds them together

```
┌──────────────────────────────────────────────────────────────┐
│ ROUTER      app/modules/<m>/router.py                        │
│             HTTP only: parse, validate, delegate.            │
│             NEVER contains business rules.                   │
├──────────────────────────────────────────────────────────────┤
│ SERVICE     app/modules/<m>/service.py                       │
│             Business rules, orchestration, transaction       │
│             boundaries. Knows NOTHING about HTTP.            │
├──────────────────────────────────────────────────────────────┤
│ REPOSITORY  app/modules/<m>/repository.py                    │
│             SQL only. Knows NOTHING about business rules.    │
├──────────────────────────────────────────────────────────────┤
│ MODEL       app/modules/<m>/models.py                        │
│             SQLAlchemy tables + constraints.                 │
└──────────────────────────────────────────────────────────────┘
```

> **★ The dependency rule: arrows point downward only.**
>
> A service may import a repository. A repository may **never** import a service.
> A service may **never** import `fastapi`.

That last clause is the one that pays off. It is what makes a service reusable from a CLI
command, a background worker, or a test — with no HTTP client involved.

### Why `models.py` and `schemas.py` are separate files

This surprises people coming from Mongoose, where one schema does everything.

| | `models.py` (SQLAlchemy) | `schemas.py` (Pydantic) |
|---|---|---|
| Describes | The **database table** | The **API contract** |
| Contains | Columns, indexes, FKs, constraints | Fields the client may send / will receive |
| Example field | `password_hash` | ✗ never exposed |
| Example field | `id`, `created_at` | ✓ in `StudentRead`, ✗ in `StudentCreate` |

You typically write three or four Pydantic schemas per model:

```python
class StudentCreate(BaseSchema):    # what the client may POST
    name: str
    admission_number: str

class StudentUpdate(BaseSchema):    # what the client may PATCH — all optional
    name: str | None = None

class StudentRead(BaseSchema):      # what the API returns
    id: UUID
    name: str
    created_at: datetime
```

Separating them is what stops mass-assignment bugs (a client POSTing
`{"role": "admin", "school_id": "<someone else's>"}` and having it silently applied) and
accidental field leaks.

---

## 8. Multi-tenancy: the thing that makes this project unusual

One database. Many schools. **A school must never see another school's data.**

Most systems attempt this with `WHERE school_id = ?` in every query. That is one
forgotten filter away from a permanent, silent data breach. This project does not rely on
it.

### Three layers, only one of which is a real boundary

| Layer | Mechanism | Strength |
|---|---|---|
| 1. Application | `WHERE school_id = ...` in queries | **Weak** — one forgotten filter leaks forever |
| 2. **Database** | **RLS policy on every tenant table** | **Strong — the database refuses** |
| 3. Role | App connects as `sms_app` (`NOBYPASSRLS`, owns nothing) | Required for layer 2 to function |

### The chain, end to end

```
1. User logs in
       → security.py signs a JWT containing a `sid` (school id) claim

2. Request arrives with that token
       → deps.py::get_current_principal verifies the signature
       → publishes school_id into a ContextVar          [core/context.py]

3. The DB session is opened
       → session.py::get_db reads that ContextVar
       → SELECT set_config('app.current_school_id', '<uuid>', true)

4. Any query runs
       → PostgreSQL appends the RLS policy predicate automatically:
             school_id = current_setting('app.current_school_id')::uuid
```

So the tenant boundary is enforced by **PostgreSQL, on every statement** — including raw
SQL, ad-hoc ORM queries, and code written by a developer who never read this document.
That is the entire point.

### Three ways to silently disable all of it

1. **Connecting as `postgres` or as the table owner.** Superusers and owners bypass RLS.
   Hence the separate `sms_app` role, and `FORCE ROW LEVEL SECURITY` on every table.
2. **Using `SET` instead of `SET LOCAL` / `set_config(..., true)`.** The value would
   survive past `COMMIT` and leak onto the next request that reuses the pooled connection.
3. **A `USING` clause with no `WITH CHECK`.** A user could *write* rows into another
   tenant even though they cannot read them back.

`alembic/rls.py` wraps the correct DDL so no migration has to get this right by hand.

### Cross-tenant reads return 404, never 403

A 403 would confirm the resource exists — which is itself a cross-tenant information
leak. Under RLS this falls out naturally: another school's row simply is not returned, so
the service sees `None` and raises `NotFoundError`.

---

## 9. How to add a new feature, start to finish

Worked example: **add a Students module.**

### Step 1 — create the module directory

```bash
mkdir -p app/modules/students && touch app/modules/students/__init__.py
```

### Step 2 — `models.py` (the database table)

```python
from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Student(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    admission_number: Mapped[str] = mapped_column(String(32))
    full_name: Mapped[str] = mapped_column(String(160))

    # Scoped to the school, not global — two schools may legitimately reuse a number.
    __table_args__ = (UniqueConstraint("school_id", "admission_number"),)
```

### Step 3 — register it in `db/registry.py` ★

```python
from app.modules.students import models as student_models  # noqa: F401
```

**Do this in the same commit.** Skipping it makes Alembic generate a `DROP TABLE`.

### Step 4 — generate and edit the migration

```bash
make migration m="add students table"
```

Then **open the generated file** in `alembic/versions/` and add the RLS calls — Alembic
cannot infer them:

```python
from alembic.rls import disable_tenant_rls, setup_tenant_table

def upgrade() -> None:
    op.create_table("students", ...)      # ← autogenerated
    setup_tenant_table("students")        # ← you add this

def downgrade() -> None:
    disable_tenant_rls("students")        # ← you add this
    op.drop_table("students")             # ← autogenerated
```

Apply it: `make migrate`

### Step 5 — `schemas.py` (the API contract)

```python
from uuid import UUID
from app.common.schemas import BaseSchema

class StudentCreate(BaseSchema):
    admission_number: str
    full_name: str

class StudentUpdate(BaseSchema):
    full_name: str | None = None

class StudentRead(BaseSchema):
    id: UUID
    admission_number: str
    full_name: str
```

Note `StudentCreate` has no `school_id` — the client must never supply it. The service
takes it from the verified token.

### Step 6 — `repository.py`

```python
from app.common.repository import BaseRepository
from app.modules.students.models import Student

class StudentRepository(BaseRepository[Student]):
    model = Student
    sortable_fields = frozenset({"full_name", "admission_number", "created_at"})

    async def get_by_admission_number(self, number: str) -> Student | None:
        return await self.find_one(Student.admission_number == number)
```

### Step 7 — `service.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import Page, PageParams
from app.core.context import require_school_id
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.students.repository import StudentRepository
from app.modules.students.schemas import StudentCreate, StudentRead


class StudentService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = StudentRepository(session)

    async def create(self, payload: StudentCreate) -> StudentRead:
        if await self.repo.get_by_admission_number(payload.admission_number):
            raise ConflictError("That admission number is already in use.")

        student = await self.repo.create(
            **payload.model_dump(),
            school_id=require_school_id(),   # from the token, never from the client
        )
        return StudentRead.model_validate(student)

    async def get(self, student_id: UUID) -> StudentRead:
        student = await self.repo.get(student_id)
        if student is None:
            raise NotFoundError("Student not found.")   # also covers cross-tenant
        return StudentRead.model_validate(student)

    async def list(self, params: PageParams) -> Page[StudentRead]:
        rows, total = await self.repo.list(params=params)
        return Page.create([StudentRead.model_validate(r) for r in rows], total, params)
```

No `fastapi` import. No `commit()`. That is the shape to aim for.

### Step 8 — `router.py`

```python
from uuid import UUID
from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, Pagination, require_roles
from app.common.schemas import Page
from app.modules.students.schemas import StudentCreate, StudentRead
from app.modules.students.service import StudentService

router = APIRouter()


@router.get("", response_model=Page[StudentRead])
async def list_students(db: DbSession, params: Pagination) -> Page[StudentRead]:
    return await StudentService(db).list(params)


@router.post(
    "",
    response_model=StudentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("school_admin", "registrar"))],
)
async def create_student(payload: StudentCreate, db: DbSession) -> StudentRead:
    return await StudentService(db).create(payload)


@router.get("/{student_id}", response_model=StudentRead)
async def get_student(student_id: UUID, db: DbSession) -> StudentRead:
    return await StudentService(db).get(student_id)
```

Every handler is one line of delegation. That is the target.

### Step 9 — mount it in `api/v1/router.py`

```python
from app.modules.students.router import router as students_router

api_router.include_router(students_router, prefix="/students", tags=["Students"])
```

### Step 10 — test and verify

```bash
make check          # lint + typecheck + tests
make dev            # then open http://localhost:8000/docs
```

### The checklist, condensed

- [ ] `models.py` — include `TenantMixin` if the table is tenant-owned
- [ ] **Add the import to `db/registry.py`**
- [ ] `make migration` — then **add `setup_tenant_table()` to the generated file**
- [ ] `make migrate`
- [ ] `schemas.py` — Create / Update / Read
- [ ] `repository.py` — set `model` and `sortable_fields`
- [ ] `service.py` — business rules; raise `AppError`s, never `HTTPException`
- [ ] `router.py` — thin handlers
- [ ] Mount in `api/v1/router.py`
- [ ] Tests
- [ ] `make check`

---

## 10. Python things that trip up MERN developers

### `__init__.py` — the empty files everywhere

A directory becomes an importable Python **package** by containing `__init__.py`. Those
zero-byte files are not clutter; delete one and `from app.core.config import Settings`
stops working. Roughly analogous to an `index.js` barrel file, except often intentionally
empty.

### Imports are absolute, from the project root

```python
from app.core.config import get_settings      # ✓
from ..core.config import get_settings        # ✗ relative — avoid
```

There is no `require()` and no `module.exports`. Every top-level name in a module is
importable by default; `_leading_underscore` is the convention for "private" (a
convention, not enforced).

### `from __future__ import annotations` at the top of every file

Makes all type annotations lazily evaluated strings. It lets you reference a class before
it is defined and use modern syntax (`str | None`) on older interpreters, and it removes
runtime cost from annotations. **Copy it into every new file** — it is the house style
here.

### Type hints are checked, not decorative

`mypy` runs in `strict` mode (`make typecheck`). Unlike TypeScript, Python does not
*enforce* types at runtime — but mypy will fail your build, and Pydantic *does* enforce
them at API boundaries.

Modern syntax used throughout (Python 3.13, so no `Optional`/`List`/`Dict`):

```python
str | None                    # not Optional[str]
list[str]                     # not List[str]
dict[str, Any]                # not Dict[str, Any]
class Page[T](BaseModel)      # PEP 695 generics, not Generic[T]
```

`ruff` will auto-fix the old forms if you slip.

### `async` looks the same but works differently

Syntax is nearly identical to JS. The difference: **Python has one event loop and it
blocks easily.** A synchronous call inside an `async def` freezes *every* concurrent
request in the process — not just the current one.

```python
import time, requests
time.sleep(1)                        # ✗ blocks the whole event loop
requests.get(url)                    # ✗ blocking HTTP library

import asyncio, httpx
await asyncio.sleep(1)               # ✓
async with httpx.AsyncClient() as c: # ✓
    await c.get(url)
```

This is exactly why the project uses `asyncpg` (not `psycopg2`) and `aiosmtplib` (not
`smtplib`). Ruff's `ASYNC` lint rules catch many of these automatically.

There is no `.then()` and no `Promise.all` — the equivalent is `asyncio.gather(...)`.

### The database has a fixed schema

The single biggest change from MongoDB. There is no "just add a field to the document".
Adding a field = edit the model + generate a migration + apply it. Every environment goes
through the same versioned migration files, in the same order.

It feels slower for the first week. It also means production can never silently contain
three different shapes of the same record.

### Virtual environments

`.venv/` is this project's `node_modules/`. Two ways to work with it:

```bash
uv run pytest                # ← recommended: uv handles the venv for you
# or
source .venv/bin/activate    # ← activate it in your shell first
pytest
```

The Makefile uses `uv run` everywhere, so `make test` works with no activation.

### `Protocol` is a TypeScript `interface`

```python
class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...
```

Structural typing: any object with a matching `send` satisfies it. No inheritance
required — which is exactly what makes test fakes trivial.

### Dataclasses vs Pydantic models

Both look like classes with typed fields. The difference is **validation**:

- `@dataclass` — a plain typed container, no validation. Used for internal objects like
  `Principal` and `EmailMessage`, where the data is already trusted.
- `BaseModel` (Pydantic) — parses and **validates**. Used at every boundary: API
  request/response bodies, and environment config.

Rule of thumb: crossing a trust boundary → Pydantic. Internal plumbing → dataclass.

### Ruff replaces four tools

`make format` = eslint --fix + prettier. `make lint` = eslint. One binary, and it is
roughly 100× faster than the Python tools it replaces.

---

## 11. Command cheat sheet

Everything runs from `backend/`.

### First-time setup

```bash
cd backend
uv venv --python 3.13         # create .venv
uv sync                       # npm install
cp .env.example .env          # then set SECRET_KEY and the DB credentials
```

Generate a real secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Bootstrap the database once, as a superuser, then migrate:

```bash
createdb school_manage_db
psql -d school_manage_db -f scripts/init-db.sql   # extensions + the sms_app role
make migrate
```

> **★ Two roles, not one.** `POSTGRES_USER` is the restricted runtime role
> (`sms_app`); `MIGRATION_USER` is the schema **owner** that Alembic connects as.
> `sms_app` has no DDL rights, so leaving `MIGRATION_USER` unset on a database it
> does not own makes `make migrate` fail with *permission denied for schema public*.
> Setting both to the owner "fixes" that and silently disables every RLS policy —
> owners are exempt from RLS. See [§8](#8-multi-tenancy-the-thing-that-makes-this-project-unusual).

Seed the first platform operator (needed to approve self-registered schools):

```bash
SMS_SUPERADMIN_PASSWORD='...' uv run python -m scripts.create_super_admin \
  --email ops@yourdomain.com --name "Ops"
```

Note the address must be a genuinely routable one — reserved TLDs (`.test`,
`.local`, `.example`) are rejected, because the login endpoint would reject them too.

### Daily

| Command | Node equivalent | Does |
|---|---|---|
| `make dev` | `npm run dev` | Hot-reload server on :8000 |
| `make test` | `npm test` | Run the suite |
| `make test-cov` | `npm test -- --coverage` | With a coverage report |
| `make lint` | `npx eslint .` | Check lint |
| `make format` | `npx eslint --fix . && npx prettier -w .` | Auto-fix + format |
| `make typecheck` | `npx tsc --noEmit` | mypy strict |
| **`make check`** | — | **lint + typecheck + test. What CI runs. Run before every commit.** |
| `make help` | `npm run` | List all targets |

### Database

| Command | Does |
|---|---|
| `make migration m="add students table"` | Generate a migration from model changes |
| `make migrate` | Apply all pending migrations |
| `make downgrade` | Roll back the most recent one |
| `make history` | Show migration history |

### Docker

| Command | Does |
|---|---|
| `make docker-up` | Start PostgreSQL + API |
| `make docker-down` | Stop (data preserved) |
| `make docker-reset` | Stop **and destroy the volume** |

### Smoke-testing auth against a running server

```bash
make dev > /tmp/sms.log 2>&1 &
SA_EMAIL=ops@yourdomain.com SA_PASSWORD='...' ./scripts/smoke_auth.sh /tmp/sms.log
```

Walks register → verify → approve → login (2FA) → refresh rotation → logout over real
HTTP. The pytest suite covers the same flows in-process; this catches the wiring the
in-process tests cannot see — middleware order, RLS binding on a pooled connection,
and the migration/runtime role split. Requires `EMAIL_BACKEND=console`, since it reads
OTP codes out of the log.

### Once running

| URL | What |
|---|---|
| http://localhost:8000/docs | Swagger UI — interactive, try endpoints live |
| http://localhost:8000/redoc | ReDoc — cleaner reference docs |
| http://localhost:8000/openapi.json | The raw spec (generate a TS client from this) |
| http://localhost:8000/health | Liveness |
| http://localhost:8000/health/ready | Readiness |

All three docs URLs are **disabled in production** — they leak the full API surface.

---

## 12. What exists vs what is still empty

### Done and working

- ✅ Application skeleton, boots with **no database** (`DB_ENABLED=false`)
- ✅ Typed, validated configuration with production safety guards
- ✅ Structured logging with automatic request/tenant correlation
- ✅ Full error-handling pipeline (RFC 9457 Problem Details)
- ✅ Password hashing (Argon2id) + JWT issue/verify
- ✅ OTP generation/verification primitives
- ✅ Email transport (console + SMTP) with HTML/plaintext templates
- ✅ Generic async repository with pagination, sorting, soft delete
- ✅ Database session management with RLS tenant binding
- ✅ Model mixins (uuid pk, timestamps, soft delete, tenant)
- ✅ Auth/tenant/role/pagination dependencies
- ✅ Health + readiness probes
- ✅ Alembic configured, with RLS migration helpers
- ✅ Docker + docker-compose, `sms_app` role bootstrap
- ✅ Test harness (unit + integration), ruff, mypy strict, Makefile

### Module 1 — Tenancy & Auth — DONE (delivered end-to-end)

- ✅ **`modules/tenancy`** — full stack: `schemas` / `repository` / `service` / `router`.
  Self-service registration (creates a PENDING_APPROVAL school), super-admin onboarding,
  approve / suspend transitions, list + filter, `GET /schools/current`.
- ✅ **`modules/auth`** — full stack across three tables. Register → email-verify (OTP) →
  login with account lockout and role-based 2FA → token issue → refresh (rotate +
  revoke-on-use) → logout → forgot / reset password (revokes all sessions) → `GET /me`.
- ✅ **`alembic/versions/`** — the bootstrap migration creates `schools`, `users`,
  `otp_codes`, `refresh_tokens`. `schools` carries a hand-written **id-based** RLS policy
  (a school *is* the tenant); the three auth tables are deliberately outside RLS with DML
  grants only. Verified: applies, downgrades, and `alembic check` reports no drift.
- ✅ `scripts/create_super_admin.py` — seed the first platform operator (uses
  `session_scope`, since there is no request context to read the tenant from).
- ✅ Tests: existing skeleton smoke tests plus DB-backed integration tests that run the
  app as the restricted `sms_app` role, including a **cross-tenant RLS isolation** suite
  proving PostgreSQL refuses cross-tenant reads *and* writes. `make check` is green.

Two foundation fixes were needed to make the above actually work, both documented at
their site:

- **Enum columns.** The status/role/plan columns were `String(32)` annotated as enums, so
  reads came back as plain `str` and the models' `is`-based `is_active` / `can_authenticate`
  always returned False (login was structurally impossible). They now use `str_enum(...)`
  (`db/base.py`): VARCHAR **+ CHECK** with `values_callable`, which is the "VARCHAR + CHECK"
  design this doc already described, and returns real `StrEnum` members.
- **`from alembic.rls import …`.** The installed `alembic` distribution shadowed the local
  `alembic/` directory, so the documented helper import never resolved. `alembic/env.py`
  now extends `alembic.__path__` so the convention works for every future migration.

### Module 2 — Academics & Students — DONE (delivered end-to-end)

- ✅ **`modules/academics`** — full stack. `SchoolClass` (grade levels) and `Section`,
  both tenant-scoped. Create/list/update/delete classes; sections nested under their
  class with optional `capacity` and a `class_teacher_id` FK to `users`. A class with
  sections, or a section with enrolled students, refuses deletion rather than
  cascading a whole grade away.
- ✅ **`modules/students`** — full stack. Directory CRUD with demographics, guardian
  and emergency contacts; search across name and admission number; filter by section
  and status; partial (PATCH) updates; soft delete. Admission numbers are unique per
  school, section capacity and the plan's `max_students` seat limit are both enforced.
- ✅ **Public admissions intake** — `POST /students/admissions` is unauthenticated and
  lands an applicant as `PENDING` with a generated admission number. It cannot be used
  to self-admit (status and admission number are server-assigned), and a suspended
  school is indistinguishable from a nonexistent one, so the endpoint leaks no tenant
  existence.
- ✅ **Class & section summaries** — `GET /classes/summary` returns each class, its
  sections, and live headcounts in two queries total (one grouped `COUNT`), not an
  N+1 per section. Pending applicants are excluded — they occupy no seat.
- ✅ **RBAC** — reads are open to any authenticated member of the school (teachers need
  the directory); every write requires `school_admin`.
- ✅ **Migration** — `classes`, `sections`, `students`, each with
  `setup_tenant_table()`. Verified: applies, downgrades cleanly, re-applies, and
  `alembic check` reports no drift.
- ✅ **Tests** — 22 new integration tests running as the restricted `sms_app` role,
  including cross-tenant isolation proofs for both modules (another school's class or
  student reads as **404, never 403**). `make check` is green: 78 tests, ruff clean,
  mypy strict clean.

Three foundation fixes were needed along the way, all documented at their site:

- **Alembic connected as the wrong role.** `env.py`'s docstring stated that migrations
  run as the schema owner while the app runs as restricted `sms_app`, but it read
  `settings.DATABASE_URL` — the *application* DSN — so `alembic upgrade` failed with
  `permission denied for schema public`. Added `MIGRATION_USER`/`MIGRATION_PASSWORD`
  and a `MIGRATION_DATABASE_URL` that `env.py` now uses, making the documented
  owner/app split real rather than aspirational.
- **The public admissions lookup could never find its school.** `schools` is itself
  RLS-protected by an *id-based* policy, so on an unauthenticated session with no
  tenant bound the predicate is `id = NULL` and every school reads as missing. The
  tenant is now bound *before* the lookup, not after.
- **`create_super_admin.py` could create an unusable account.** It writes straight to
  the table, bypassing the `EmailStr` check on the API schemas, so an address in a
  reserved TLD (`.test`, `.local`) was accepted and then rejected with a 422 by
  `POST /auth/login` — a super admin that exists but can never sign in. The script now
  validates with the same validator the login endpoint uses.

### Not started

- ⬜ **Attendance, timetable, fees**, and the rest of the checklist — see [§13](#13-the-product-feature-checklist)
- ⬜ No frontend directory (config anticipates Next.js on :3000)
- ⬜ No CI pipeline file

### The remaining build order

1. ✅ **`modules/tenancy`** — the `schools` table (done).
2. ✅ **`modules/auth`** — users, login, refresh, OTP state (done).
3. ✅ **`modules/academics`** — classes and sections (done).
4. ✅ **`modules/students`** — the SIS directory and admissions intake (done).
5. **`modules/attendance`** — next. Reads the section register that `academics` now
   provides; the PDF's "under 10 seconds" target makes it a bulk-write endpoint
   (one request per section per day), not one POST per student.
6. Then: timetable, fees + PDF vouchers, communications (WhatsApp), documents
   (ID cards, certificates), global search, inventory/POS, and the AI modules.

### Where to look when you are stuck

| Question | File |
|---|---|
| Why is the architecture like this? | [backend/README.md](backend/README.md) |
| What environment variables exist? | [.env.example](backend/.env.example) + [core/config.py](backend/app/core/config.py) |
| What commands can I run? | `make help` / [Makefile](backend/Makefile) |
| How do I get the DB session / current user? | [api/deps.py](backend/app/api/deps.py) |
| What CRUD do I get for free? | [common/repository.py](backend/app/common/repository.py) |
| Which error should I raise? | [core/exceptions.py](backend/app/core/exceptions.py) |
| How does tenant isolation work? | [db/session.py](backend/app/db/session.py) + [alembic/rls.py](backend/alembic/rls.py) |
| How do I write a test? | [tests/conftest.py](backend/tests/conftest.py) |

**One habit worth forming:** every source file in this project starts with a docstring
explaining *why it exists*, *what it is responsible for*, and *what it interacts with*.
Before changing a file, read its docstring. Before adding a file, write one.

---

## 13. The product feature checklist

Source: `school_management_complete_features.pdf` — 18 features across 9 categories.
This table is the single place where the product checklist and the codebase are
reconciled. **Update it in the same commit that ships a feature.**

Status: ✅ done · 🟡 partial · ⬜ not started

### Tenant & Access Control

| Feature | Priority | Status | Where |
|---|---|---|---|
| Multi-Tenant RLS Database | Critical | ✅ | `alembic/rls.py`, `db/session.py`; policies on `schools`, `classes`, `sections`, `students` |
| Super Admin Dashboard | Critical | 🟡 | API done (`modules/tenancy`: list/onboard/approve/suspend). No UI — there is no frontend yet |
| Role-Based Access Control | High | ✅ | `api/deps.py::require_roles`; School Admin writes, Teacher reads |

### Student Management (SIS)

| Feature | Priority | Status | Where |
|---|---|---|---|
| Student Directory CRUD | Critical | ✅ | `modules/students` — demographics, guardian + emergency contacts, search, soft delete |
| Class & Section Setup | Critical | ✅ | `modules/academics` — grades and sections, capacity, class teacher |
| Digital Admissions Form | High | 🟡 | Backend done: `POST /students/admissions` → PENDING queue. The Next.js form itself is not built |

### Academics & Daily Ops

| Feature | Priority | Status | Where |
|---|---|---|---|
| Fast Attendance Interface | Critical | ⬜ | Next module. Will read the section register from `academics` |
| Basic Timetable View | Medium | ⬜ | — |
| Class & Section Summaries | High | ✅ | `GET /classes/summary` — sections + headcount per class |

### Financials

| Feature | Priority | Status | Where |
|---|---|---|---|
| Fee Structure Configuration | Critical | ⬜ | Will key off `classes` (fees are per grade) |
| Automated PDF Vouchers | High | ⬜ | Needs a PDF library — none added yet |
| Payment Collection Dashboard | Critical | ⬜ | — |

### Communications

| Feature | Priority | Status | Where |
|---|---|---|---|
| WhatsApp Integration (API) | High | ⬜ | `students.guardian_phone` is the target field, already captured |
| Bulk Fee WhatsApp Notifications | Critical | ⬜ | Depends on fees + WhatsApp |

### ID Cards & Certificates

| Feature | Priority | Status | Where |
|---|---|---|---|
| Student ID Card Generator | Medium | ⬜ | `students.photo_url` and `schools.logo_url` exist for it |
| Certificate Generator | Medium | ⬜ | — |

### Global Navigation & Search

| Feature | Priority | Status | Where |
|---|---|---|---|
| Global Search Engine | High | 🟡 | Per-module search exists (`GET /students?q=`); `pg_trgm` is installed. No cross-entity omnibar yet |

### AI Agents & Automation

| Feature | Priority | Status | Where |
|---|---|---|---|
| AI Homework Agent | High | ⬜ | — |
| AI WhatsApp Notification Agent | High | ⬜ | — |

### Stationary & Inventory

| Feature | Priority | Status | Where |
|---|---|---|---|
| Stationary Point of Sale (POS) | Medium | ⬜ | — |

### AI Marketing Studio

| Feature | Priority | Status | Where |
|---|---|---|---|
| AI Social Media Designer | High | ⬜ | — |
| Print & Paper Design Hub | Medium | ⬜ | — |

### A note on what "done" means here

Every ✅ above is backend only — API endpoints, business rules, migrations and tests.
**There is no frontend in this repository.** Several checklist items (the Super Admin
dashboard, the admissions form, ID card templates, the marketing studio) are described
in the PDF as Next.js interfaces; for those, a ✅ backend is roughly half the feature.
The 🟡 rows are exactly the ones where the API exists and the UI does not.
