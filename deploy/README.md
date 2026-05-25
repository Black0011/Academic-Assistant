# Deploying the Academic Agent Framework

A self-contained Docker Compose stack that runs the FastAPI backend, the
ARQ worker, the React SPA (served by Nginx with `/api/` reverse-proxied
to the backend), Postgres, and Redis. Designed for **a single private
server** — typically Ubuntu 22.04 / Debian 12 / any host with Docker 24+.

> Production-ready for a small team (≤10 users). For multi-tenant SaaS
> you'll want to add an edge proxy that terminates TLS and a managed
> Postgres — see [§ HTTPS](#https) below.

---

## Prerequisites

| Tool          | Minimum version | Notes |
| ------------- | --------------- | ----- |
| Docker Engine | 24.0            | `docker --version` |
| Docker Compose | v2.20          | bundled with modern Docker; `docker compose version` |
| `git`         | any             | clone the repo |

System resources: **2 vCPU / 4 GB RAM / 20 GB disk** is comfortable.
Postgres + Redis idle around 200 MB; the API/worker pair plus chrome
(if enabled) push it to ~1.2 GB working set.

---

## Five-minute install

```bash
# 1. Clone
git clone <your-fork-or-mirror> academic-agent-framework
cd academic-agent-framework

# 2. Configure
cp .env.example .env
# edit .env — minimum:
#   AAF_SECRET_KEY=<openssl rand -hex 32>
#   POSTGRES_PASSWORD=<openssl rand -hex 16>
#   AUTH_DISABLED=false        (keep true if single-user/local-only)
#   plus AT LEAST ONE LLM provider key (OPENAI_API_KEY, ANTHROPIC_API_KEY, …)

# 3. Build + boot
docker compose up -d --build

# 4. Smoke test
curl http://localhost:8080/api/health           # → {"status":"ok"}
curl http://localhost:8080/api/version          # → version + memory backends
open  http://localhost:8080/                    # SPA
```

The first registered user becomes `admin`. After onboarding, set
`AUTH_ALLOW_SIGNUP=false` and `docker compose up -d` to disable
self-signup.

---

## What runs where

```
                       ┌────────── browser ──────────┐
                       │ http://<host>:8080          │
                       └──────────────┬──────────────┘
                                      │ HTTP/1.1
                                      ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  frontend  (Nginx + Vite SPA)                                │
   │  • /         → static dist/ (SPA fallback)                   │
   │  • /api/     → reverse proxy → backend:8000                  │
   │  • /api/tasks/.../stream → SSE: buffering off, 1 h read t/o  │
   └──────────────────────────────────────────────────────────────┘
                                      │ docker-network
                                      ▼
   ┌─────────────────────────────────┐    ┌─────────────────────┐
   │ backend  (FastAPI / uvicorn)    │    │ worker  (ARQ)       │
   │ /api/* + lifespan               │ ←→ │ executes long-tasks │
   └─────────────────────────────────┘    └─────────────────────┘
                  │                                 │
        ┌─────────┴───────┐                ┌────────┴────────┐
        ▼                 ▼                ▼                 ▼
   ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
   │ postgres │     │ /data    │     │ redis    │     │ /data    │
   │  16-     │     │ volume   │     │ 7.2      │     │ volume   │
   │  alpine  │     │ (host    │     │ (queue + │     │          │
   │          │     │  bind)   │     │ session) │     │          │
   └──────────┘     └──────────┘     └──────────┘     └──────────┘
```

| Service    | Image               | Internal port | External port | Persists to |
| ---------- | ------------------- | ------------- | ------------- | ----------- |
| `frontend` | `aaf-web` (Nginx)   | 80            | `${AAF_HTTP_PORT:-8080}` | — |
| `backend`  | `aaf-backend`       | 8000          | (none)        | `./data/`   |
| `worker`   | `aaf-backend`       | (none)        | (none)        | `./data/`   |
| `postgres` | `postgres:16-alpine`| 5432          | (none)        | `postgres_data` volume |
| `redis`    | `redis:7.2-alpine`  | 6379          | (none)        | `redis_data` volume |
| `minio` *  | `minio/minio`       | 9000 / 9001   | `${MINIO_API_PORT}` / `${MINIO_CONSOLE_PORT}` | `minio_data` volume |

`*` only starts when you opt-in via `--profile storage`.

Only `frontend` is exposed externally. Everything else is reachable
via the docker network only — no Postgres-exposed-to-internet
foot-guns.

---

## Bind mounts

| Host path  | Container path     | Direction | Purpose |
| ---------- | ------------------ | --------- | ------- |
| `./skills` | `/app/skills`      | read-only | L1 capability skill scripts |
| `./rules`  | `/app/rules`       | read-only | L2 behaviour rules |
| `./data`   | `/data`            | read-write | knowledge cards, heuristics, sessions, users, chroma vectors, Postgres dumps if you enable the backup script |

Postgres + Redis use named docker volumes (`postgres_data`,
`redis_data`); they survive `docker compose down`. To wipe everything:

```bash
docker compose down --volumes
rm -rf data/
```

---

## Day 2 operations

### Logs

```bash
docker compose logs -f --tail=200            # everything
docker compose logs -f backend worker        # just app code
```

The backend emits structured JSON logs (`structlog`). Pipe to your
favourite shipper.

### Updating

```bash
git pull
docker compose build
docker compose up -d
```

Compose only restarts containers whose image hash actually changed; the
DB and Redis stay up.

### Backups

`deploy/backup.sh` does a Postgres `pg_dump`, tars the `./data/` dir,
and (commented-out) mirrors MinIO via `mc`. Run it from cron:

```cron
30 3 * * *   cd /opt/aaf && AAF_BACKUP_ROOT=/var/backups/aaf bash deploy/backup.sh
```

Restore:

```bash
docker compose exec -T postgres pg_restore -U aaf -d aaf -c < postgres-<TS>.dump
tar -xzf data-<TS>.tar.gz
```

### Resetting an admin password

The YAML user store at `data/users/<id>.yaml` is editable by hand.
Replace `password_hash` with the output of:

```bash
docker compose run --rm backend python -c \
  "from backend.core.auth.password import hash_password; print(hash_password('newpass'))"
```

---

## HTTPS

The bundled stack speaks plain HTTP on `${AAF_HTTP_PORT}`. There are
two supported paths to TLS, in increasing order of "lives in this repo":

### Option A — terminate TLS upstream

If you already run an edge proxy (Caddy / Traefik / Nginx / cloud load
balancer), point it at `localhost:${AAF_HTTP_PORT}`:

```caddy
your.domain.com {
    reverse_proxy localhost:8080
}
```

The frontend image already sets sane forwarded-headers handling
(`X-Forwarded-Proto`, `X-Real-IP`); the backend ASGI server is
launched with `--proxy-headers --forwarded-allow-ips '*'`, so URLs
generated server-side honour the outer scheme.

### Option B — use the bundled production overlay (recommended)

`docker-compose.prod.yml` adds a `caddy` service that terminates TLS,
provisions Let's Encrypt certificates automatically, and replaces the
host port mapping on `frontend` so only Caddy is exposed:

```bash
cp deploy/caddy/Caddyfile.example deploy/caddy/Caddyfile
# edit deploy/caddy/Caddyfile if you want a custom hostname embedded
# instead of the {$AAF_DOMAIN} env-var form

# in .env:
#   AAF_DOMAIN=your.domain.com
#   AAF_ACME_EMAIL=admin@your.domain.com
#   AAF_TLS_HTTPS_PORT=443     (or any host port if 443 is taken)

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Verification:

```bash
curl https://your.domain.com/healthz       # → {"status":"ok"}
curl -I https://your.domain.com/           # → HTTP/2 200, HSTS header set
```

Caddy stores issued certificates in the `caddy_data` volume, so they
survive `docker compose down` (without `--volumes`). The Caddyfile
includes an SSE-specific reverse_proxy block that disables buffering
to keep `/api/tasks/.../stream` live.

For local TLS without public DNS (e.g. `https://localhost`), set
`AAF_DOMAIN=localhost` and Caddy will generate an internal CA + a
self-signed cert on first boot — install the CA root into your trust
store via `docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| `curl /api/health` returns 502 | backend hasn't passed its healthcheck yet | wait ~20 s; `docker compose logs backend` |
| SSE events arrive in bursts | a proxy somewhere is buffering | ensure your edge proxy mirrors the SSE-specific block in `deploy/nginx/frontend.conf` |
| Worker not picking up tasks | `AAF_TASK_QUEUE_BACKEND` not set to `arq` *or* worker container is unhealthy | `docker compose logs worker`; confirm Redis URL |
| `/api/version` shows `MockLLMProvider` | no LLM credentials present | set at least one provider key in `.env` and `docker compose up -d` |
| Login fails after enabling auth | `AUTH_DISABLED` was true at first user creation, so admin doesn't exist yet | `AUTH_DISABLED=false`, restart, register the first user |

---

## Pre-flight checklist (production)

- [ ] `AAF_SECRET_KEY` is at least 32 random hex chars (rotate it = invalidate all sessions)
- [ ] `POSTGRES_PASSWORD` is *not* the default
- [ ] `AUTH_DISABLED=false` and `AUTH_ALLOW_SIGNUP=false` after onboarding
- [ ] At least one LLM key is wired and `/api/version` shows it instead of `MockLLMProvider`
- [ ] `./data/` lives on a backed-up disk
- [ ] HTTPS is terminated upstream of the `frontend` service (or the production overlay is active)
- [ ] `docker compose ps` shows all five services as `healthy`
- [ ] If running the production overlay: `caddy` is `running` and `https://<domain>/healthz` returns 200
