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
from .rate_limit import api_limiter
from .routers import (
    auth,
    claims,
    dashboard,
    exports,
    jobs,
    projects,
    providers,
    sandbox as sandbox_router,
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
    reaper = None
    if settings.inline_worker:
        thread = threading.Thread(
            target=worker_loop, args=(stop_event,), daemon=True, name="distill-worker"
        )
        thread.start()
        logger.info("inline worker started as %s", settings.worker_id)
    if settings.sandbox:
        # Free the seat at boot: a restart kills in-flight work, and leaving the
        # old visit "active" would lock the demo out until its timer drained.
        from .db import SessionLocal
        from .sandbox import recover_on_startup, reaper_loop

        db = SessionLocal()
        try:
            recover_on_startup(db)
        except Exception as exc:  # pragma: no cover - never block startup
            logger.warning("sandbox recovery skipped: %s", exc)
        finally:
            db.close()
        reaper = threading.Thread(
            target=reaper_loop, args=(stop_event,), daemon=True, name="sandbox-reaper"
        )
        reaper.start()
        logger.info(
            "sandbox mode: one seat, %s min per visit", settings.sandbox_visit_minutes
        )
    _app.state.started_at = time.time()
    try:
        yield
    finally:
        stop_event.set()
        for worker_thread in (thread, reaper):
            if worker_thread:
                # Give an in-flight stage a chance to finish its transaction
                # instead of killing the process mid-commit.
                worker_thread.join(timeout=15)
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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach browser-side hardening headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=(), interest-cohort=()"
    )
    # The SPA needs inline styles from Tailwind's runtime and its own bundle; no
    # third-party script origins are required, so keep the policy tight.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'",
    )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Coarse per-identity throttle.

    Auth endpoints keep their own stricter buckets, so they are excluded here to
    avoid double counting a single failed login as two requests.
    """
    path = request.url.path
    if settings.multiuser and path.startswith(settings.api_prefix) and not path.startswith(
        f"{settings.api_prefix}/health"
    ) and not path.startswith(f"{settings.api_prefix}/ready") and "/auth/" not in path:
        from .deps import SESSION_COOKIE, client_ip

        identity = request.cookies.get(SESSION_COOKIE, "")[:24] or client_ip(request)
        allowed, retry = api_limiter.take(f"api:{identity}")
        if not allowed:
            return JSONResponse(
                {"detail": "请求过于频繁，请稍后重试"},
                status_code=429,
                headers={"Retry-After": str(int(retry) + 1)},
            )
    return await call_next(request)


for router in (
    auth.router,
    sandbox_router.router,
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