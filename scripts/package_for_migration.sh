#!/usr/bin/env bash
# Package the AAF source tree for migration to a personal machine / server.
#
# What we include  : source code, schemas, prompts, skills, docs, deploy
#                    config, sdk, scripts, tests, AGENTS.md / PLAN.md.
# What we include  : data/ (knowledge cards, manuscripts, user store) — your
#                    actual experiments live here. Comment the line out below
#                    if you'd rather start from a clean slate on the new box.
# What we exclude  : .venv, node_modules, dist/build artefacts, *.cache,
#                    .git*, IDE state, the sqlite DB (regen'd on first boot),
#                    and any .env (avoid leaking secrets onto USB / Drive).
#
# Output: aaf-migration-YYYYMMDD-HHMM.tar.gz in $HOME, plus a SHA-256 sum.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, regardless of how invoked

STAMP="$(date +%Y%m%d-%H%M)"
# Default output is the parent of the project so it's easy to AirDrop /
# scp without packaging the project into itself. Override with OUT=...
# if you want it elsewhere (e.g. /Volumes/USB/...).
OUT="${OUT:-$(cd .. && pwd)/aaf-migration-${STAMP}.tar.gz}"

# Use --exclude per pattern. Order matters slightly: more specific first.
TAR_EXCLUDES=(
  "--exclude=.venv"
  "--exclude=node_modules"
  "--exclude=frontend/node_modules"
  "--exclude=frontend/dist"
  "--exclude=*.pyc"
  "--exclude=__pycache__"
  "--exclude=.mypy_cache"
  "--exclude=.pytest_cache"
  "--exclude=.ruff_cache"
  "--exclude=.git"
  "--exclude=.cursor"
  "--exclude=.DS_Store"
  "--exclude=.env"
  "--exclude=.env.local"
  "--exclude=data/aaf.db"          # SQLite — recreated on first boot
  "--exclude=data/aaf.db-shm"
  "--exclude=data/aaf.db-wal"
  "--exclude=data/chroma"          # local vector store; rebuilds from knowledge
  "--exclude=*.log"
)

cd ..
tar -czf "$OUT" "${TAR_EXCLUDES[@]}" "$(basename "$OLDPWD")"

# Quick integrity hash so the receiver can verify the transfer.
shasum -a 256 "$OUT" | tee "${OUT}.sha256"

# Human-readable summary.
size_human="$(du -h "$OUT" | awk '{print $1}')"
file_count="$(tar -tzf "$OUT" | wc -l | tr -d ' ')"

cat <<EOF

---------------------------------------------------------------
✓ packaged $file_count files into $size_human
  archive : $OUT
  sha256  : $(awk '{print $1}' "${OUT}.sha256")

Next steps:
  1. AirDrop / USB / personal cloud → copy $OUT to the target machine
  2. On the target machine, run:
       tar -xzf aaf-migration-${STAMP}.tar.gz
       cd academic-agent-framework
       bash scripts/bootstrap_target.sh
---------------------------------------------------------------
EOF
