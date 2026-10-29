from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..llm import PROTOCOL_LABELS, capabilities_for
from ..models import Job, Project, Provider, Skill, Source
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
def usage_overview(db: Session = Depends(get_db)):
    """Aggregate provider token usage per project.

    Only totals that a provider actually reported are summed. When no model has
    been called, ``calls`` is 0 and every token field is absent — the UI must
    show "未统计" rather than a fabricated 0.
    """
    rows: dict[str, dict] = {}
    jobs = db.scalars(select(Job)).all()
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

    projects = {
        project.id: project.name
        for project in db.scalars(select(Project).where(Project.id.in_(list(rows)))).all()
    } if rows else {}
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
def stats(db: Session = Depends(get_db)):
    """Single query endpoint for the dashboard health strip."""
    counts = {
        "projects": db.scalar(select(func.count()).select_from(Project)) or 0,
        "sources": db.scalar(select(func.count()).select_from(Source)) or 0,
        "skills": db.scalar(select(func.count()).select_from(Skill)) or 0,
        "providers": db.scalar(select(func.count()).select_from(Provider)) or 0,
        "jobs": db.scalar(select(func.count()).select_from(Job)) or 0,
        "jobs_active": db.scalar(
            select(func.count()).select_from(Job).where(Job.status.in_(["queued", "running"]))
        ) or 0,
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
