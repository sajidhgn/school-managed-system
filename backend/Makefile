# Developer command surface.
#
# WHY A MAKEFILE: it is the discoverable, self-documenting entry point for every
# routine task. New developers run `make help` instead of hunting through the
# README for the right uv incantation, and CI runs the exact same targets a
# developer runs locally -- so "passes on my machine" and "passes in CI" mean the
# same thing.

.DEFAULT_GOAL := help
.PHONY: help install dev dev-live test test-cov lint format typecheck check migrate migration downgrade docker-up docker-down waha-up waha-down clean seed seed-demo seed-superadmin verify-user reconcile maintenance send-whatsapp process-books reconcile-ledger mfa-enroll openapi db db-reset db-tunnel db-tunnel-stop db-tunnel-status

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Install all dependencies including dev tools
	uv sync

dev: db  ## Run the API with hot reload on :8000 (local database)
	$(UV_RUN) uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-live:  ## Run the API with hot reload on :8000 (LIVE VPS database)
	@$(MAKE) --no-print-directory dev live=1

test:  ## Run the test suite
	uv run pytest

test-cov:  ## Run tests with a coverage report
	uv run pytest --cov --cov-report=term-missing --cov-report=html

lint:  ## Check for lint errors
	uv run ruff check .

format:  ## Auto-fix lint errors and format
	uv run ruff check --fix .
	uv run ruff format .

typecheck:  ## Run mypy in strict mode
	uv run mypy app

check: lint typecheck test  ## Run the full quality gate (what CI runs)

# --- Database ---------------------------------------------------------------

migration: db  ## Generate a migration: make migration m="add students table"
	@test -n "$(m)" || (echo "Usage: make migration m=\"description\"" && exit 1)
	$(UV_RUN) alembic revision --autogenerate -m "$(m)"

migrate: db  ## Apply all pending migrations
	$(UV_RUN) alembic upgrade head

downgrade: db  ## Roll back the most recent migration
	$(UV_RUN) alembic downgrade -1

history:  ## Show migration history
	uv run alembic history --verbose

# --- Local vs live database -------------------------------------------------
#
# Every target that talks to the database lists `db` as a prerequisite and runs
# through $(UV_RUN). By default that is the LOCAL database configured in .env.
# Add `live=1` (`make migrate live=1`, or `make dev-live`) to target the VPS
# database instead: `db` opens the SSH tunnel and $(UV_RUN) overlays .env.live on
# top of .env. Real environment variables beat .env in pydantic-settings, so
# .env.live only holds the keys that differ -- POSTGRES_HOST=127.0.0.1,
# POSTGRES_PORT=15432 and the live POSTGRES_PASSWORD / MIGRATION_PASSWORD.
# Local is the default so a bare `make migrate` can never touch production.
#
# `rawai-db` is defined in ~/.ssh/config (forwards 15432 -> VPS 127.0.0.1:5432) and
# is shared with the rawai project, so "already running" is the normal case.
# `test` needs neither: the integration suite uses its own local database.

ifeq ($(live),1)
UV_RUN := uv run --env-file .env.live
else
UV_RUN := uv run
endif

# `ss` is Linux-only and macOS ships `lsof` instead; either answers whether
# something is already listening on 15432.
TUNNEL_UP = { ss -ltn 'sport = :15432' 2>/dev/null || lsof -nP -iTCP:15432 -sTCP:LISTEN 2>/dev/null; } | grep -q LISTEN

db:
ifeq ($(live),1)
	@test -f .env.live || { echo "Missing .env.live -- see the 'Local vs live database' notes in the Makefile"; exit 1; }
	@$(MAKE) --no-print-directory db-tunnel
	@echo ">> Database: LIVE (VPS via 127.0.0.1:15432)"
else
	@echo ">> Database: local (.env)"
endif

db-tunnel:  ## Open the SSH tunnel to the VPS database (127.0.0.1:15432)
	@if $(TUNNEL_UP); then \
		echo "Tunnel already running on 127.0.0.1:15432"; \
	elif ssh -f -N rawai-db; then \
		echo "Tunnel started on 127.0.0.1:15432"; \
	else \
		echo "Could not open the tunnel -- check: ssh rawai-vps true"; exit 1; \
	fi

db-tunnel-stop:  ## Close the SSH tunnel to the VPS database
	@pkill -f '^ssh -f -N rawai-db$$|^ssh -N rawai-db$$' && echo "Tunnel stopped" || echo "No tunnel running"

db-tunnel-status:  ## Show whether the VPS database tunnel is up
	@$(TUNNEL_UP) && echo "Tunnel UP (127.0.0.1:15432)" || echo "Tunnel DOWN -- run: make db-tunnel"

db-reset:  ## DESTRUCTIVE: drop the schema, re-migrate, re-seed. Local only.
	@echo "This DROPS every table in $${POSTGRES_DB:-school_manage_db}. Ctrl-C within 3s to abort."
	@sleep 3
	psql -h $${POSTGRES_HOST:-localhost} -U postgres -d $${POSTGRES_DB:-school_manage_db} \
		-c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	psql -h $${POSTGRES_HOST:-localhost} -U postgres -d $${POSTGRES_DB:-school_manage_db} \
		-f scripts/init-db.sql
	$(MAKE) migrate
	$(MAKE) seed

# --- Seeding ----------------------------------------------------------------
#
# `seed` is idempotent and safe to re-run: the permission catalog is upserted (so a
# new permission ships with a seed run) while plans are insert-if-absent (so a
# re-run never resets a price the super admin negotiated).

seed: db  ## Seed permissions, plans and the super admin (idempotent)
	$(UV_RUN) python -m app.cli seed

seed-demo: db  ## Seed + create a demo org with two schools, staff and invitations
	$(UV_RUN) python -m app.cli seed --demo

# Fills an EXISTING organization -- the one you already sign in as -- so the app has
# something to render. Additive and safe to re-run: campuses, classes and staff are
# topped up to the target, and anything you created by hand is left alone.
seed-dummy: db  ## Populate an org with demo data: make seed-dummy org=cambridge-int
	@test -n "$(org)" || (echo "Usage: make seed-dummy org=<organization-slug>" && exit 1)
	$(UV_RUN) python scripts/seed_dummy_data.py --org-slug "$(org)" \
		--schools $${schools:-5} --classes $${classes:-10} \
		--min-students $${min_students:-20} --max-students $${max_students:-30}

# `seed` only CREATES the super admin -- it never rewrites an existing one, so a
# changed .env password, a lockout after five bad guesses, or a deactivated account
# all survive a re-run. There is no emailed reset for this role by design, so this
# is the out-of-band recovery path: it converges the account onto .env.
seed-superadmin: db  ## Create or repair the platform super admin from .env
	$(UV_RUN) python scripts/seed_super_admin.py

reconcile: db  ## Recompute organization usage counters from source tables
	$(UV_RUN) python -m app.cli reconcile-usage

maintenance: db  ## Daily pass: billing lifecycle, retention, scheduled challan generation, late fees
	$(UV_RUN) python -m app.cli run-maintenance

send-whatsapp: db  ## Post queued WhatsApp group messages (pywhatkit: run on the logged-in desktop; watch=1 keeps draining)
	$(UV_RUN) python -m app.cli send-whatsapp $(if $(watch),--watch,)

process-books: db  ## Run the book agent on queued chapters (watch=1 to keep polling)
	$(UV_RUN) python -m app.cli process-books $(if $(watch),--watch,)

reconcile-ledger: db  ## Report students whose fee ledger disagrees with their vouchers
	$(UV_RUN) python -m app.cli reconcile-ledger

mfa-enroll: db  ## Enroll/rotate platform TOTP: make mfa-enroll email=admin@example.com
	@test -n "$(email)" || (echo "Usage: make mfa-enroll email=admin@example.com" && exit 1)
	$(UV_RUN) python -m app.cli mfa-enroll --email "$(email)"

# Signup leaves an account `pending` and emails a link; login refuses until it is
# clicked. Locally that mail may bounce, land in spam, or go to a throwaway address,
# leaving the account unreachable. This consumes a real token through the real
# verification path -- so the subscription and audit row are created exactly as the
# emailed link would create them.
verify-user: db  ## Verify a signup's email locally: make verify-user email=owner@example.com
	@test -n "$(email)" || (echo "Usage: make verify-user email=owner@example.com" && exit 1)
	$(UV_RUN) python -m app.cli verify-user --email "$(email)"

openapi:  ## Regenerate openapi.json (the frontend generates its types from this)
	uv run python scripts/dump_openapi.py

# --- Docker -----------------------------------------------------------------

docker-up:  ## Start the local stack (PostgreSQL + API)
	docker compose up --build -d

docker-down:  ## Stop the stack (data volume is preserved)
	docker compose down

waha-up:  ## Start the WAHA WhatsApp gateway on :3001 (for WHATSAPP_BACKEND=waha)
	docker compose --profile waha up -d waha

waha-down:  ## Stop the WAHA gateway (linked sessions are kept in its volume)
	docker compose --profile waha stop waha

docker-reset:  ## Stop the stack AND destroy the database volume
	docker compose down -v

clean:  ## Remove caches and build artefacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
