# Developer command surface.
#
# WHY A MAKEFILE: it is the discoverable, self-documenting entry point for every
# routine task. New developers run `make help` instead of hunting through the
# README for the right uv incantation, and CI runs the exact same targets a
# developer runs locally -- so "passes on my machine" and "passes in CI" mean the
# same thing.

.DEFAULT_GOAL := help
.PHONY: help install dev test test-cov lint format typecheck check migrate migration downgrade docker-up docker-down clean

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
