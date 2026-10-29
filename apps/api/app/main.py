from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT_DIR, settings
from .db import healthcheck, init_db
from .errors import install_error_handlers
from .logging_setup import configure_logging
from .routers import (
    claims,
    dashboard,
    exports,
    jobs,
    projects,
    providers,
    search,
    settings as settings_router,
    skills,
    sources,
)
from .version import PIPELINE_VERSION
from .worker import worker_loop

logger = logging.getLogger("distill.app")

VERSION = PIPELINE_VERSION
WEB_DIST = settings.web_dist


def _resolve_web_dist() -> Path:
    """Locate the built frontend.

    Supports three layouts: source checkout (``apps/web/dist``), container image
    (``/app/web``), and an explicit ``DISTILL_WEB_DIST`` override for a CDN-less
    split deployment.
    """
    candidates = [
        WEB_DIST,
        ROOT_DIR / "web",
        ROOT_DIR / "apps" / "web" / "dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return WEB_DIST


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings.ensure_dirs()
    init_db()
    stop_event = threading.Event()
    thread = None
    if settings.inline_worker:
        thread = threading.Thread(
            target=worker_loop, args=(stop_event,), daemon=True, name="distill-worker"
        )
        thread.start()
        logger.info("inline worker started as %s", settings.worker_id)
    _app.state.started_at = time.time()
    try:
        yield
    finally:
        stop_event.set()
        if thread:
            # Give an in-flight stage a chance to finish its transaction instead
            # of killing the process mid-commit.
            thread.join(timeout=15)
        logger.info("shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=VERSION,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.is_production else "/openapi.json",
)
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"
    if request.url.path.startswith(settings.api_prefix) and elapsed_ms > 1500:
        logger.warning(
            "slow request",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "duration_ms": round(elapsed_ms, 1),
                "status": response.status_code,
            },
        )
    return response


for router in (
    projects.router,
    sources.router,
    providers.router,
    jobs.router,
    claims.router,
    search.router,
    skills.router,
    exports.router,
    dashboard.router,
    settings_router.router,
):
    app.include_router(router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health", tags=["ops"])
def health():
    """Liveness: process is up and can serve requests. Never touches the DB."""
    return {
        "status": "ok",
        "version": VERSION,
        "uptime_seconds": round(time.time() - getattr(app.state, "started_at", time.time()), 1),
        "worker": "inline" if settings.inline_worker else "external",
    }


@app.get(f"{settings.api_prefix}/ready", tags=["ops"])
def ready():
    """Readiness: dependencies are usable, so traffic can be routed here."""
    checks: dict[str, object] = {}
    ok = True
    try:
        checks["database"] = healthcheck()
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)[:300]}
        ok = False
    for name, path in (("data_dir", settings.data_dir), ("export_dir", settings.export_dir)):
        writable = path.exists() and path.is_dir()
        checks[name] = {"path": str(path), "status": "ok" if writable else "missing"}
        ok = ok and writable
    try:
        from .vector_store import embedding_service

        checks["vector"] = {
            "status": "ok",
            "backend": embedding_service.backend,
            "sqlite_vec": embedding_service.vec_available(),
            "dim": settings.embedding_dim,
        }
    except Exception as exc:
        checks["vector"] = {"status": "degraded", "detail": str(exc)[:200]}
    payload = {"status": "ready" if ok else "degraded", "version": VERSION, "checks": checks}
    return JSONResponse(payload, status_code=200 if ok else 503)


_web_root = _resolve_web_dist()
if (_web_root / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_web_root / "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def frontend(full_path: str):
    if full_path.startswith(("api/", "docs", "openapi.json", "redoc")):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index = _web_root / "index.html"
    if index.exists():
        target = _web_root / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(index)
    return JSONResponse(
        {
            "message": "蒸馏平台 API 已启动。请先构建前端：pnpm --dir apps/web build",
            "docs": "/docs",
            "health": f"{settings.api_prefix}/health",
            "ready": f"{settings.api_prefix}/ready",
        }
    )