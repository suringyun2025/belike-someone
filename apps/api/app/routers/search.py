from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project
from ..vector_store import index_chunks, search_chunks, vector_status

router = APIRouter(tags=["search"])


def _project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.get("/projects/{project_id}/search")
def search_project(
    project_id: str,
    q: str = "",
    limit: int = 8,
    db: Session = Depends(get_db),
):
    _project(db, project_id)
    return search_chunks(db, project_id, q, limit=min(max(limit, 1), 50))


@router.post("/projects/{project_id}/index")
def index_project(project_id: str, force: bool = False, db: Session = Depends(get_db)):
    _project(db, project_id)
    try:
        return index_chunks(db, project_id, force=force)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"索引失败：{exc}") from exc


@router.get("/projects/{project_id}/vector-status")
def get_vector_status(project_id: str, db: Session = Depends(get_db)):
    _project(db, project_id)
    return vector_status(db, project_id)
