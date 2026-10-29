# ---------------------------------------------------------------------------
# 蒸馏平台 · 本地一键启动（Windows PowerShell）
#
#   powershell -ExecutionPolicy Bypass -File deploy\scripts\start.ps1
#
# 与 start.sh 等价：校验依赖、迁移、构建前端、启动。
# ---------------------------------------------------------------------------
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root

$bind = if ($env:DISTILL_BIND) { $env:DISTILL_BIND } else { "127.0.0.1" }
$port = if ($env:DISTILL_PORT) { $env:DISTILL_PORT } else { "8000" }

foreach ($tool in @("uv", "node", "pnpm")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "缺少依赖：$tool"
    }
}

Write-Host "==> 安装后端依赖" -ForegroundColor Cyan
uv sync --project apps/api

Write-Host "==> 安装前端依赖" -ForegroundColor Cyan
pnpm install --dir apps/web --frozen-lockfile

if (-not (Test-Path "apps/web/dist/index.html")) {
    Write-Host "==> 构建前端" -ForegroundColor Cyan
    pnpm --dir apps/web build
} else {
    Write-Host "==> 前端产物已存在，跳过构建" -ForegroundColor DarkGray
}

Write-Host "==> 应用数据库迁移" -ForegroundColor Cyan
uv run --project apps/api alembic upgrade head

Write-Host "==> 启动 http://${bind}:${port}" -ForegroundColor Green
uv run --project apps/api uvicorn app.main:app `
    --app-dir apps/api `
    --host $bind --port $port `
    --proxy-headers --timeout-graceful-shutdown 20