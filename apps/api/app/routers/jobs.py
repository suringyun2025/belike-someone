from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import AuditEvent, Claim, Job, Project, Source, StageRun, utcnow
from ..pipeline import create_job
from ..schemas import JobCreate, JobOut
from .common import job_out

router = APIRouter(tags=["jobs"])
TERMINAL = {"completed", "failed", "cancelled", "waiting_for_review"}


def _get_job(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.post("/projects/{project_id}/jobs", response_model=JobOut, status_code=201)
def start_job(project_id: str, payload: JobCreate, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if payload.kind == "distill":
        source_count = len(
            db.scalars(select(Source).where(Source.project_id == project_id)).all()
        )
        if source_count == 0:
            raise HTTPException(status_code=400, detail="请先上传资料")
    else:
        approved = len(
            db.scalars(
                select(Claim).where(
                    Claim.project_id == project_id, Claim.status == "approved"
                )
            ).all()
        )
        if approved == 0:
            raise HTTPException(status_code=400, detail="请先批准至少一条断言")
    config = {
        "provider_id": payload.provider_id or project.provider_id,
        "run_llm_evals": payload.run_llm_evals,
    }
    job = create_job(db, project_id, payload.kind, config)
    return job_out(job)


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
def list_jobs(project_id: str, db: Session = Depends(get_db)):
    jobs = db.scalars(
        select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(100)
    ).all()
    return [job_out(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return job_out(_get_job(db, job_id))


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    async def stream():
        last_payload = ""
        while True:
            db = SessionLocal()
            try:
                job = db.get(Job, job_id)
                if not job:
                    yield "event: error\ndata: {\"error\":\"任务不存在\"}\n\n"
                    return
                payload = json.dumps(
                    job_out(job).model_dump(mode="json"), ensure_ascii=False
                )
                if payload != last_payload:
                    yield f"data: {payload}\n\n"
                    last_payload = payload
                status = job.status
            finally:
                db.close()
            if status in TERMINAL:
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _audit(db: Session, job: Job, action: str, detail: dict | None = None) -> None:
    db.add(
        AuditEvent(
            project_id=job.project_id,
            action=action,
            detail={"job_id": job.id, **(detail or {})},
        )
    )


@router.post("/jobs/{job_id}/pause", response_model=JobOut)
def pause_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if job.status in TERMINAL:
        raise HTTPException(status_code=400, detail="任务已结束，无法暂停")
    job.pause_requested = True
    if job.status == "queued":
        job.status = "paused"
    db.add(job)
    _audit(db, job, "job.pause")
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.post("/jobs/{job_id}/resume", response_model=JobOut)
def resume_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if job.status != "paused":
        raise HTTPException(status_code=400, detail="只有暂停中的任务可以恢复")
    job.pause_requested = False
    job.status = "queued"
    db.add(job)
    _audit(db, job, "job.resume")
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if job.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="任务已结束")
    job.cancel_requested = True
    if job.status in {"queued", "paused", "waiting_for_review"}:
        job.status = "cancelled"
        job.finished_at = utcnow()
    db.add(job)
    _audit(db, job, "job.cancel")
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="只有失败或取消的任务可以重试")
    failed = db.scalar(
        select(StageRun)
        .where(StageRun.job_id == job.id, StageRun.status == "failed")
        .order_by(StageRun.created_at)
        .limit(1)
    )
    if failed:
        failed.status = "pending"
        failed.error = ""
        failed.attempt += 1
        db.add(failed)
    job.status = "queued"
    job.error = ""
    job.finished_at = None
    job.cancel_requested = False
    job.pause_requested = False
    db.add(job)
    _audit(db, job, "job.retry", {"stage": failed.stage if failed else ""})
    db.commit()
    db.refresh(job)
    return job_out(job)
