#!/usr/bin/env bash
# pack-for-migration.sh — 打包学术助手的功能性文件用于迁移
# 用法: bash scripts/pack-for-migration.sh [输出路径]
#
# 排除:
#   - 个人数据 (data/knowledge/*.yaml, data/manuscripts/, data/chroma/, data/*.db)
#   - 环境文件 (.env.laptop, data/runtime/provider.yaml)
#   - 缓存/构建产物 (.venv, node_modules, __pycache__, dist, .mypy_cache, etc.)
#   - IDE 私有配置 (.claude/)
#   - Git 内部 (.git/)
#
# 包含:
#   - 所有源码 (backend/, frontend/src/, skills/, rules/, prompts/)
#   - 配置模板 (.env.example, .env.laptop.example, config/)
#   - 部署文件 (deploy/, docker-compose*.yml, Makefile)
#   - 文档 (README.md, SETUP.md, PLAN.md, AGENTS.md, docs/)
#   - L3 启发式 (data/skills/) + 占位文件 (data/*/.keep)
#   - SDK, CLI, scripts
#   - 前端构建所需的配置 (package.json, tsconfig.json, vite.config.ts 等)
#   - Python 依赖锁 (pyproject.toml, uv.lock)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

OUTPUT="${1:-academic-agent-framework.tar.gz}"

echo "==> Packing academic-agent-framework for migration..."
echo "    Output: $OUTPUT"

tar czf "$OUTPUT" \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.mypy_cache' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='node_modules' \
    --exclude='frontend/dist' \
    --exclude='.claude' \
    --exclude='.env.laptop' \
    --exclude='.env.local' \
    --exclude='.env' \
    --exclude='data/runtime/provider.yaml' \
    --exclude='data/chroma' \
    --exclude='data/manuscripts' \
    --exclude='data/proposals' \
    --exclude='data/papers' \
    --exclude='data/documents' \
    --exclude='data/users' \
    --exclude='data/knowledge/*.yaml' \
    --exclude='data/*.db' \
    --exclude='data/*.db-shm' \
    --exclude='data/*.db-wal' \
    -C "$(dirname "$PROJECT_ROOT")" \
    "$(basename "$PROJECT_ROOT")"

SIZE=$(du -sh "$OUTPUT" | awk '{print $1}')
echo "==> Done! $OUTPUT ($SIZE)"
echo ""
echo "To restore on another machine:"
echo "  tar xzf $OUTPUT"
echo "  cd academic-agent-framework"
echo "  cat SETUP.md"
