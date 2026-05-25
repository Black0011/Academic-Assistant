#!/usr/bin/env bash
# Run this on the personal machine / VPS *after* extracting the migration
# tarball. Idempotent — safe to re-run if it fails halfway.
#
# Prerequisites on the target box:
#   • Python ≥ 3.11 (we recommend `uv` which manages its own toolchain)
#   • Node.js ≥ 20  (for the frontend dev server)
#
# What it does:
#   1. Verifies tools exist; if missing, prints the one-liner to install.
#   2. Creates a fresh .env from .env.example so you can plug in keys.
#   3. Installs Python deps (uv) and Node deps (npm).
#   4. Smoke-tests the backend can import.
#   5. Prints next-step commands to start dev / docker.
set -euo pipefail

cd "$(dirname "$0")/.."

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }

bold "1/5  checking toolchain"

if ! command -v uv >/dev/null 2>&1; then
  red "uv not found. Install with:"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
green "  ✓ uv $(uv --version)"

if ! command -v node >/dev/null 2>&1; then
  red "node not found. Install (macOS): brew install node"
  echo "    Or use nvm: https://github.com/nvm-sh/nvm"
  exit 1
fi
green "  ✓ node $(node --version)"

if ! command -v npm >/dev/null 2>&1; then
  red "npm not found (should ship with node)."
  exit 1
fi
green "  ✓ npm $(npm --version)"

bold "2/5  preparing .env"
if [ ! -f .env ]; then
  cp .env.example .env
  green "  ✓ created .env from .env.example"
  echo "    edit it to add AAF_OPENAI_API_KEY (or your preferred provider)"
else
  green "  ✓ .env already present, leaving alone"
fi

bold "3/5  installing python deps (this is the slow one)"
uv sync
green "  ✓ python deps ready in .venv/"

bold "4/5  installing frontend deps"
npm --prefix frontend install
green "  ✓ frontend deps ready in frontend/node_modules/"

bold "5/5  smoke-test"
uv run python -c "from backend.app import create_app; print('  ✓ backend imports cleanly')"

cat <<EOF

---------------------------------------------------------------
✓ bootstrap complete

Next steps:

  Dev mode (foreground, two tabs):
      Tab 1: make dev-backend
      Tab 2: make dev-frontend
      Open  http://127.0.0.1:5173

  All-in-one Docker (recommended for a personal server):
      docker compose up -d
      Open  http://<host>:5173

  Production with TLS (Caddy):
      see deploy/README.md for the 5-minute install

  Smoke test:
      uv run pytest -x -q

Edit .env first to plug in an LLM API key — without one, the framework
boots fine but Research / Write workflows fall back to a mock provider.
---------------------------------------------------------------
EOF
