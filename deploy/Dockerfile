# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# 蒸馏平台 · 多阶段镜像
#
# 阶段划分的目的是让运行镜像尽可能小，并且不包含 Node、编译器和源码依赖：
#   web    -> 构建前端静态资源
#   python -> 安装 Python 依赖（含可选 OCR/ASR 扩展）
#   runtime-> 只复制产物，非 root 运行
#
# 平台：linux/amd64、linux/arm64 均可构建（依赖均为纯 Python 或 wheel）。
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=22

# --------------------------------- 前端构建 ---------------------------------
FROM node:${NODE_VERSION}-slim AS web

WORKDIR /build
RUN corepack enable && corepack prepare pnpm@10 --activate

# 先只复制清单文件，让依赖层可以命中缓存。
COPY apps/web/package.json apps/web/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

COPY apps/web/ ./
# `build` 会先跑 tsc --noEmit 再做 vite build，类型错误会让构建失败。
RUN pnpm build

# --------------------------------- 后端依赖 ---------------------------------
FROM python:${PYTHON_VERSION}-slim AS python

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN pip install --no-cache-dir "uv>=0.9"

WORKDIR /build
COPY apps/api/pyproject.toml apps/api/uv.lock ./
# 可选能力：--build-arg DISTILL_EXTRAS=ocr,asr
ARG DISTILL_EXTRAS=""
RUN if [ -n "$DISTILL_EXTRAS" ]; then \
        uv sync --frozen --no-dev --no-install-project --extra "$DISTILL_EXTRAS"; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi

# --------------------------------- 运行镜像 ---------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    DISTILL_ENV=production \
    DISTILL_DATA_DIR=/data \
    DISTILL_EXPORT_DIR=/exports \
    DISTILL_WEB_DIST=/app/web \
    DISTILL_INLINE_WORKER=true

# tini 负责信号转发，保证 SIGTERM 能让 uvicorn 优雅停机；
# libgomp 是 ONNX Runtime 的运行时依赖（fastembed / rapidocr 需要）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "$APP_GID" app \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=python /build/.venv /app/.venv
COPY apps/api/app /app/app
COPY apps/api/migrations /app/migrations
COPY apps/api/alembic.ini /app/alembic.ini
COPY apps/api/pyproject.toml /app/pyproject.toml
COPY --from=web /build/dist /app/web

RUN mkdir -p /data /exports && chown -R app:app /app /data /exports

USER app

EXPOSE 8000
VOLUME ["/data", "/exports"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status==200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
# 单进程 uvicorn：worker 线程与应用共享 SQLite 连接，多进程在这里没有收益。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "20"]