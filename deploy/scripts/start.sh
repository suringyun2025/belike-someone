#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 蒸馏平台 · 本地一键启动（无 Docker）
#
# 适用于 macOS / Linux / WSL / Git Bash。Windows 原生请用 start.ps1。
# 会校验依赖、执行迁移、构建前端（首次），然后启动 API + worker。
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${DISTILL_BIND:-127.0.0.1}"
PORT="${DISTILL_PORT:-8000}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "缺少依赖：$1" >&2; exit 1; }
}

need uv
need node
need pnpm

echo "==> 安装后端依赖"
uv sync --project apps/api

echo "==> 安装前端依赖"
pnpm install --dir apps/web --frozen-lockfile

if [ ! -f apps/web/dist/index.html ]; then
  echo "==> 构建前端"
  pnpm --dir apps/web build
else
  echo "==> 前端产物已存在，跳过构建（改动前端后请手动 pnpm --dir apps/web build）"
fi

echo "==> 应用数据库迁移"
uv run --project apps/api alembic upgrade head

echo "==> 启动 http://$HOST:$PORT"
exec uv run --project apps/api uvicorn app.main:app \
  --app-dir apps/api \
  --host "$HOST" --port "$PORT" \
  --proxy-headers --timeout-graceful-shutdown 20