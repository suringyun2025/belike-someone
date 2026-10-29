from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, owned_project
from ..models import Project, User
from ..vector_store import index_chunks, search_chunks, vector_status

router = APIRouter(tags=["search"])


def _project(db: Session, project_id: str, user: User) -> Project:
    return owned_project(project_id, db, user)


@router.get("/projects/{project_id}/search")
def search_project(
    project_id: str,
    q: str = "",
    limit: int = 8,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _project(db, project_id, user)
    return search_chunks(db, project_id, q, limit=min(max(limit, 1), 50))


@router.post("/projects/{project_id}/index")
def index_project(
    project_id: str,
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _project(db, project_id, user)
    try:
        return index_chunks(db, project_id, force=force)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"索引失败：{exc}") from exc


@router.get("/projects/{project_id}/vector-status")
def get_vector_status(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    _project(db, project_id, user)
    return vector_status(db, project_id)
