# syntax=docker/dockerfile:1.7
#
# Backend image for the FastAPI app *and* the ARQ worker — they share
# the same Python environment but flip CMD via compose.
#
#   API     →  uvicorn backend.app:create_app --factory
#   Worker  →  arq backend.workers.arq_worker.WorkerSettings
#
# Build:
#   docker build -f deploy/backend.Dockerfile -t aaf-backend .
# Smoke:
#   docker run --rm -p 8000:8000 -e AAF_SECRET_KEY=demo aaf-backend
#   curl http://localhost:8000/api/health   # → {"status":"ok"}

# ---------- Stage 1: builder -----------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Build deps for any wheels that don't ship a manylinux build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /build

# Copy only files required to resolve dependencies first — keeps the
# layer cache warm when only application code changes.
COPY pyproject.toml README.md ./
COPY backend/ ./backend/

# Install into an isolated venv we can copy into the runtime stage.
RUN uv venv /opt/venv \
    && . /opt/venv/bin/activate \
    && uv pip install --no-cache .

# ---------- Stage 2: runtime -----------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    AAF_ENV=production \
    AAF_LOG_LEVEL=INFO

# Runtime-only system deps. `libmagic1` is consumed by python-magic if any
# tool plugin needs it; `curl` powers the HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libmagic1 \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1001 --create-home --shell /bin/bash aaf

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# `backend` is already installed inside the venv as a wheel during the
# builder stage — no need to copy the source again. Mountpoints for
# runtime-mutable / read-only assets are pre-created so the image still
# boots when run without compose binds.
RUN mkdir -p /app/skills /app/rules /data \
    && chown -R aaf:aaf /app /data

USER aaf

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "backend.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
