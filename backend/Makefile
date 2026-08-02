# Developer command surface.
#
# WHY A MAKEFILE: it is the discoverable, self-documenting entry point for every
# routine task. New developers run `make help` instead of hunting through the
# README for the right uv incantation, and CI runs the exact same targets a
# developer runs locally -- so "passes on my machine" and "passes in CI" mean the
# same thing.

.DEFAULT_GOAL := help
.PHONY: help install dev test test-cov lint format typecheck check migrate migration downgrade docker-up docker-down clean seed seed-demo reconcile openapi db-reset

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Install all dependencies including dev tools
	uv sync

dev:  ## Run the API with hot reload on :8000
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

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

migration:  ## Generate a migration: make migration m="add students table"
	@test -n "$(m)" || (echo "Usage: make migration m=\"description\"" && exit 1)
	uv run alembic revision --autogenerate -m "$(m)"

migrate:  ## Apply all pending migrations
	uv run alembic upgrade head

downgrade:  ## Roll back the most recent migration
	uv run alembic downgrade -1

history:  ## Show migration history
	uv run alembic history --verbose

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

seed:  ## Seed permissions, plans and the super admin (idempotent)
	uv run python -m app.cli seed

seed-demo:  ## Seed + create a demo org with two schools, staff and invitations
	uv run python -m app.cli seed --demo

reconcile:  ## Recompute organization usage counters from source tables
	uv run python -m app.cli reconcile-usage

openapi:  ## Regenerate openapi.json (the frontend generates its types from this)
	uv run python scripts/dump_openapi.py

# --- Docker -----------------------------------------------------------------

docker-up:  ## Start the local stack (PostgreSQL + API)
	docker compose up --build -d

docker-down:  ## Stop the stack (data volume is preserved)
	docker compose down

docker-reset:  ## Stop the stack AND destroy the database volume
	docker compose down -v

clean:  ## Remove caches and build artefacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
