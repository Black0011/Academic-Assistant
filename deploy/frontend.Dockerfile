# syntax=docker/dockerfile:1.7
#
# Frontend image — Vite SPA served by Nginx, which also reverse-proxies
# `/api/` (and the `/api/tasks/*/stream` SSE endpoint) to the backend
# service on the docker network.
#
# Build (FROM THE REPO ROOT — context = . so we can pull
# deploy/nginx/frontend.conf and frontend/* in one shot):
#
#   docker build -f deploy/frontend.Dockerfile -t aaf-web .
#
# Smoke:
#   docker run --rm -p 8080:80 aaf-web
#   curl http://localhost:8080/        # → SPA shell

# ---------- Stage 1: build ------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /build

# Lockfile + manifest first so dep installs are cached independently
# from source code.
COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY frontend/ ./

# Vite reads VITE_API_BASE at build time. Empty = same-origin (correct
# behind nginx). We pin it at the image level so users don't need any
# runtime config.
ENV VITE_API_BASE=""

RUN npm run build


# ---------- Stage 2: runtime ----------------------------------------------
FROM nginx:1.27-alpine AS runtime

RUN rm /etc/nginx/conf.d/default.conf

COPY deploy/nginx/frontend.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1/ || exit 1
