from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..llm import PROTOCOL_LABELS, capabilities_for
from ..models import Job, Project, Provider, Skill, Source, User
from ..prompts import DIMENSION_LABELS
from ..schemas import SettingsOut
from ..version import PIPELINE_VERSION

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsOut)
def get_settings():
    return SettingsOut(
        data_dir=str(settings.data_dir),
        export_dir=str(settings.export_dir),
        database_url=settings.database_url,
        inline_worker=settings.inline_worker,
        chunk_chars=settings.chunk_chars,
        chunk_overlap=settings.chunk_overlap,
        max_chunks_per_job=settings.max_chunks_per_job,
        max_upload_mb=settings.max_upload_mb,
    )


@router.get("/meta")
def meta():
    return {
        "version": PIPELINE_VERSION,
        "env": settings.env,
        "dimensions": [
            {"value": key, "label": label} for key, label in DIMENSION_LABELS.items()
        ],
        "protocols": [
            {"value": key, "label": label, "capabilities": capabilities_for(key)}
            for key, label in PROTOCOL_LABELS.items()
        ],
        "skill_spec": {
            "name_max": 64,
            "description_max": 1024,
            "compatibility_max": 500,
            "validator": "npm i -g skills-ref && skills-ref validate <path>",
        },
    }


@router.get("/usage")
def usage_overview(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Aggregate provider token usage per project.

    Only totals that a provider actually reported are summed. When no model has
    been called, ``calls`` is 0 and every token field is absent — the UI must
    show "未统计" rather than a fabricated 0.
    """
    rows: dict[str, dict] = {}
    jobs_query = select(Job)
    if settings.multiuser:
        # Only jobs belonging to the caller's projects; usage is billing data.
        jobs_query = jobs_query.where(
            Job.project_id.in_(select(Project.id).where(Project.owner_id == user.id))
        )
    jobs = db.scalars(jobs_query).all()
    for job in jobs:
        usage = job.usage or {}
        totals = usage.get("totals") or {}
        if not totals:
            continue
        entry = rows.setdefault(
            job.project_id,
            {
                "project_id": job.project_id,
                "project_name": "",
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "jobs": 0,
                "models": {},
            },
        )
        entry["calls"] += int(totals.get("calls") or 0)
        entry["jobs"] += 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            entry[key] += int(totals.get(key) or 0)
        for model, model_usage in (usage.get("by_model") or {}).items():
            bucket = entry["models"].setdefault(
                model, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            )
            bucket["calls"] += int(model_usage.get("calls") or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                bucket[key] += int(model_usage.get(key) or 0)

    if rows:
        project_scope = select(Project).where(Project.id.in_(list(rows)))
        if settings.multiuser:
            project_scope = project_scope.where(Project.owner_id == user.id)
        projects = {project.id: project.name for project in db.scalars(project_scope).all()}
        # Drop any id that escaped the scope (defence in depth).
        rows = {key: value for key, value in rows.items() if key in projects}
    else:
        projects = {}
    for project_id, entry in rows.items():
        entry["project_name"] = projects.get(project_id, project_id)

    totals = {
        "calls": sum(entry["calls"] for entry in rows.values()),
        "input_tokens": sum(entry["input_tokens"] for entry in rows.values()),
        "output_tokens": sum(entry["output_tokens"] for entry in rows.values()),
        "total_tokens": sum(entry["total_tokens"] for entry in rows.values()),
    }
    return {
        "totals": totals,
        "projects": sorted(rows.values(), key=lambda item: item["total_tokens"], reverse=True),
        "note": "仅统计供应商实际返回的用量；未返回时不估算。",
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Single endpoint for the dashboard health strip.

    Tenant scoping uses an explicit ``EXISTS`` subquery rather than
    ``IN (SELECT ...)`` inside a ``select_from(model)``: mixing the two makes
    SQLAlchemy treat the subquery's table as a second FROM element, which
    produces a cartesian product and inflates every count.
    """
    multi = settings.multiuser

    def _owned_project_exists(model) -> object:
        """Correlate ``model.project_id`` to a project the caller owns."""
        from sqlalchemy import exists

        condition = Project.id == model.project_id
        if multi:
            condition = condition & (Project.owner_id == user.id)
        return exists(select(Project.id).where(condition, Project.deleted_at.is_(None)))

    def _count(model, *where):
        stmt = select(func.count()).select_from(model)
        if where:
            stmt = stmt.where(*where)
        return db.scalar(stmt) or 0

    project_where: list = [Project.deleted_at.is_(None)]
    if multi:
        project_where.append(Project.owner_id == user.id)

    scoped = [_owned_project_exists] if multi else []

    counts = {
        "projects": _count(Project, *project_where),
        "sources": _count(Source, *[f(Source) for f in scoped]),
        "skills": _count(Skill, *[f(Skill) for f in scoped]),
        "providers": _count(Provider, *([Provider.owner_id == user.id] if multi else [])),
        "jobs": _count(Job, *[f(Job) for f in scoped]),
        "jobs_active": _count(
            Job, *[f(Job) for f in scoped], Job.status.in_(["queued", "running"])
        ),
    }
    return {
        **counts,
        "runtime": {
            "version": PIPELINE_VERSION,
            "env": settings.env,
            "database": "postgresql" if not settings.is_sqlite else "sqlite",
            "inline_worker": settings.inline_worker,
            "worker_id": settings.worker_id,
            "lease_seconds": settings.worker_lease_seconds,
        },
    }
