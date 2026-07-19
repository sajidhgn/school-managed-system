# syntax=docker/dockerfile:1.9
#
# Multi-stage build.
#
# WHY MULTI-STAGE: the builder stage carries uv, build toolchains and caches. None
# of that belongs in the image that runs in production -- every extra binary is
# attack surface. Only the virtualenv and application code are copied forward,
# which typically cuts the final image from ~1.2GB to ~250MB.

# ---------------------------------------------------------------------------
# Stage 1: build the virtualenv
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency files are copied FIRST, alone. Docker caches layers by content, so as
# long as pyproject.toml/uv.lock are unchanged this expensive layer is reused --
# turning a code-only rebuild from minutes into seconds.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Application code changes on every commit, so it is copied last.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

# Run as an unprivileged user. If the process is ever compromised, the attacker
# lands as `appuser` with no write access to the application code.
RUN groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid appuser --create-home appuser

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/app /app/app
COPY --from=builder --chown=appuser:appuser /app/alembic /app/alembic
COPY --from=builder --chown=appuser:appuser /app/alembic.ini /app/alembic.ini

USER appuser

EXPOSE 8000

# The orchestrator uses this to decide whether to route traffic here.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# NOTE: no --reload, and no --workers. Process count is the orchestrator's job --
# in Kubernetes you scale replicas, not in-container workers, so that each process
# gets its own health check and memory limit.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
