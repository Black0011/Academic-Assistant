---
name: aaf-deploy
description: >-
  Conventions for AAF deployment artifacts: Dockerfiles, docker-compose,
  Nginx config, secrets, backup/restore. Load when editing files under
  deploy/ or docker-compose.yml.
domain: engineering
triggers:
  - docker
  - dockerfile
  - docker-compose
  - nginx
  - deploy
  - deployment
  - backup
version: "1.0.0"
---

# AAF Deployment — Conventions

## 1. Core principle

Anyone should be able to:

```bash
git clone <repo>
cd academic-agent-framework
cp .env.example .env     # edit at minimum one LLM API key
docker compose up -d
# open http://localhost:8080
```

and have a working instance in **under 5 minutes on a clean Ubuntu / macOS machine**. Anything that breaks this is a bug.

## 2. Service topology (canonical)

```
nginx (optional, prod only) → frontend (static) + backend (FastAPI)
backend / worker → postgres, redis, chroma (embedded in backend), minio
```

All services are declared in `docker-compose.yml`. Profiles:

- **default**: `postgres`, `redis`, `minio` — enough for `make dev` to talk to real storage
- **`full`**: adds `backend`, `worker`, `frontend` — full stack containerised
- **`prod`**: adds `nginx`

`docker compose --profile full up -d` for full containerisation.

## 3. Dockerfile rules

- **Multi-stage builds** always.
- Builder stage installs deps; runtime stage copies only the venv/dist.
- **Python 3.11-slim** for backend; **node:20-alpine** → `nginx:1.25-alpine` for frontend.
- `HEALTHCHECK` on every long-running service.
- Never `COPY .` at the start. Be precise — `COPY pyproject.toml ./` first for layer cache.
- Don't bake secrets into images. Use env / mounted files only.

## 4. Volume layout (host → container)

| Host | Container | Mode | Reason |
|---|---|---|---|
| `./skills` | `/app/skills` | ro | L1 capability assets, updated from outside |
| `./rules` | `/app/rules` | ro | L2 rules, same |
| `./prompts` | `/app/prompts` | rw | Allow runtime prompt overrides |
| `./data` | `/data` | rw | User's papers, vectors, heuristics, sessions |
| `postgres_data` (named) | `/var/lib/postgresql/data` | rw | DB |
| `redis_data` (named) | `/data` | rw | Redis AOF |
| `minio_data` (named) | `/data` | rw | Object storage |

Never mount `backend/` into the container in production. Source goes into the image.

## 5. Environment variables

See `.env.example` — **all** configuration flows through it. Each new ENV var:

- [ ] Added to `.env.example` with a comment
- [ ] Added to `backend/settings.py` as a Pydantic Settings field with a default
- [ ] Documented in `docs/deployment.md`
- [ ] Propagated into `docker-compose.yml` if it affects containers

## 6. Secrets

- Secrets come from `.env` or Docker secrets (in prod). Never from config files checked into git.
- `SECRET_KEY` must be rotated away from `change-me-...` before any public deploy.
- `*_API_KEY` vars should be left empty in `.env.example`.

## 7. Nginx

Two nginx configs:

- `deploy/nginx/default.conf` — outer reverse proxy in `prod` profile (443/80 → backend + frontend)
- `deploy/nginx/frontend.conf` — inside the frontend image (SPA fallback)

SSE rules (critical):

```
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 24h;
```

Don't omit these or browsers will see stalls.

## 8. Backup & restore

`deploy/backup.sh` does:

1. `pg_dump -F c` → binary dump
2. `tar -czf data-<ts>.tar.gz data/` — everything except Chroma WAL files
3. (Optional) `mc mirror` MinIO → remote

Restore:

```bash
docker compose exec postgres pg_restore -U aaf -d aaf /backup/postgres-<ts>.dump
tar -xzf data-<ts>.tar.gz
make up
uv run python scripts/rebuild_chroma.py   # rebuild from knowledge YAMLs
```

## 9. Upgrades

- Never force-push to main.
- Each release tags `v<major>.<minor>.<patch>`.
- Database migrations via Alembic; migration files reviewed like code.
- Provide an `UPGRADE.md` when a release has breaking changes.

## 10. Resource sizing (document, don't enforce)

- **Minimum**: 4 core / 8GB RAM / 20GB disk — works for remote LLM only.
- **Recommended**: 8 core / 32GB RAM / 200GB disk.
- **Local LLM (7B–14B)**: add a GPU with ≥ 16GB VRAM; run Ollama/vLLM alongside.

## 11. Checklist for changing deployment

- [ ] `docker compose config` passes
- [ ] `docker compose up -d` on a clean machine works
- [ ] Every new ENV var in `.env.example`
- [ ] `Makefile` targets still work (`make up`, `make down`, `make logs`)
- [ ] `docs/deployment.md` updated
- [ ] No secret values in commits (pre-commit hook to catch)
