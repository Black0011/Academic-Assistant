# Academic Agent Framework — common dev commands
# Usage:  make <target>
#
# Requires: uv (Python), pnpm (frontend), docker compose (deploy).

.DEFAULT_GOAL := help
.PHONY: help dev up down restart logs test fmt lint typecheck migrate clean ps \
        consistency check fe-typecheck fe-build install-hooks \
        compose-build compose-pull deploy-smoke \
        dev-laptop up-lite down-lite

help:  ## Show this help
	@awk 'BEGIN{FS=":.*##"; printf "\nTargets:\n"} /^[a-zA-Z_-]+:.*##/{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Install Python + frontend deps
	@uv sync --all-extras
	@npm --prefix frontend install || true

dev:  ## Run backend (reload, port 8000) and frontend (vite, port 5173) together
	@(uv run uvicorn backend.app:create_app --factory --reload --host 127.0.0.1 --port 8000 &) \
		&& (npm --prefix frontend run dev &) \
		&& wait

dev-backend:  ## Run only backend with reload (http://127.0.0.1:8000)
	@uv run uvicorn backend.app:create_app --factory --reload --host 127.0.0.1 --port 8000

dev-frontend:  ## Run only frontend (http://127.0.0.1:5173, proxies /api → :8000)
	@npm --prefix frontend run dev

dev-laptop:  ## Laptop preset: backend (sqlite, in-memory queue) + frontend, reads .env.laptop
	@if [ ! -f .env.laptop ]; then \
		echo "==> .env.laptop not found. Copy from .env.laptop.example:"; \
		echo "    cp .env.laptop.example .env.laptop"; \
		exit 1; \
	fi
	@(uv run --env-file .env.laptop uvicorn backend.app:create_app --factory --reload --host 127.0.0.1 --port 8000 &) \
		&& (npm --prefix frontend run dev &) \
		&& wait

up:  ## Build (if needed) + start the full M6 stack in the background
	@docker compose up -d --build

up-lite:  ## Laptop docker stack (backend + frontend only, sqlite + inmemory queue)
	@docker compose -f docker-compose.lite.yml up -d --build

down:  ## docker compose down (containers only — volumes survive)
	@docker compose down

down-lite:  ## Tear down the lite stack (sqlite file under ./data survives)
	@docker compose -f docker-compose.lite.yml down

restart:  ## Recreate API + worker + web (keeps DB/Redis warm)
	@docker compose up -d --no-deps --build backend worker frontend

logs:  ## Follow compose logs (last 100 lines)
	@docker compose logs -f --tail=100

ps:  ## Show service status
	@docker compose ps

compose-build:  ## Rebuild aaf-backend + aaf-web images
	@docker compose build backend frontend

compose-pull:  ## Pull updated 3rd-party images (postgres / redis / minio)
	@docker compose pull postgres redis

deploy-smoke:  ## Hit the running stack on $${AAF_HTTP_PORT:-8080} to confirm it's serving
	@PORT=$${AAF_HTTP_PORT:-8080}; \
	  echo "GET /api/health"; curl --fail --silent http://localhost:$$PORT/api/health  | head -c 200; echo; \
	  echo "GET /api/version"; curl --fail --silent http://localhost:$$PORT/api/version | head -c 400; echo

test:  ## Run backend tests
	@uv run pytest backend/tests -v

fmt:  ## Format code
	@uv run ruff format .
	@pnpm -C frontend run format || true

lint:  ## Lint code
	@uv run ruff check .
	@pnpm -C frontend run lint || true

typecheck:  ## Type-check Python
	@uv run mypy backend

fe-typecheck:  ## Type-check the frontend (tsc -b --noEmit)
	@npm --prefix frontend run typecheck

fe-build:  ## Build the production frontend bundle
	@npm --prefix frontend run build

consistency:  ## Run mechanical structure invariants (fast, stdlib only)
	@uv run python scripts/check_consistency.py

check: lint typecheck consistency test fe-typecheck  ## The merge gate
	@echo "OK · all checks passed"

install-hooks:  ## Point git at .githooks (one-time per clone)
	@git config core.hooksPath .githooks
	@echo "hooks installed — pre-commit will run scripts/check_consistency.py"

migrate:  ## Apply Alembic migrations
	@uv run alembic -c backend/db/alembic.ini upgrade head

migrate-new:  ## Create a new migration (make migrate-new msg="add x")
	@uv run alembic -c backend/db/alembic.ini revision --autogenerate -m "$(msg)"

patch-skills:  ## Re-run the M0 frontmatter patcher (idempotent)
	@uv run python scripts/patch_skill_frontmatter.py

code-index:  ## Build code index database (.code-reading/index.db)
	@uv run python scripts/code_indexer.py .

clean:  ## Clean caches
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov
