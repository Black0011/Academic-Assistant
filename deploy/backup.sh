#!/usr/bin/env bash
# Simple backup script for private deployments.
# Tars data/, dumps Postgres, mirrors MinIO. Run via cron.

set -euo pipefail

TS=$(date +%Y%m%d-%H%M%S)
ROOT=${AAF_BACKUP_ROOT:-./backups}
mkdir -p "$ROOT"

echo "[1/3] Postgres dump..."
docker compose exec -T postgres pg_dump -U aaf -F c aaf > "$ROOT/postgres-$TS.dump"

echo "[2/3] Data directory..."
tar -czf "$ROOT/data-$TS.tar.gz" --exclude='data/chroma/*.log' data/

echo "[3/3] (optional) MinIO mirror — configure remote and uncomment:"
# mc mirror local/aaf s3-remote/aaf-$TS

echo "Backup complete: $ROOT/*-$TS.*"
