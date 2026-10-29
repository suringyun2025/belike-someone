from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user, owned_project
from ..models import AuditEvent, Claim, Conflict, Project, Provider, User, utcnow
from ..prompts import DIMENSION_LABELS
from ..schemas import (
    PersonaDimensionOut,
    PersonaOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from .common import project_out

router = APIRouter(prefix="/projects", tags=["projects"])


def _owned(db: Session, project_id: str, user: User) -> Project:
    """Single entry point for project lookups so ownership cannot be forgotten."""
    return owned_project(project_id, db, user)


def _audit(db: Session, project_id: str | None, action: str, user: User, detail: dict) -> None:
    db.add(
        AuditEvent(
            project_id=project_id,
            actor_id=user.id,
            actor=user.email,
            action=action,
            detail=detail,
        )
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = select(Project).where(Project.deleted_at.is_(None))
    if settings.multiuser:
        query = query.where(Project.owner_id == user.id)
    projects = db.scalars(query.order_by(Project.updated_at.desc())).all()
    return [project_out(db, project) for project in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    if payload.provider_id:
        provider = db.get(Provider, payload.provider_id)
        # A provider must belong to the caller, otherwise project creation is a
        # way to attach someone else's credentials.
        if not provider or (settings.multiuser and provider.owner_id != user.id):
            raise HTTPException(status_code=400, detail="指定的模型配置不存在")

    if settings.multiuser:
        limit = user.max_projects or settings.max_projects_per_user
        current = db.scalar(
            select(func.count())
            .select_from(Project)
            .where(Project.owner_id == user.id, Project.deleted_at.is_(None))
        ) or 0
        if current >= limit:
            raise HTTPException(status_code=403, detail=f"项目数量已达上限（{limit}）")

    project = Project(
        name=payload.name.strip(),
        codename=payload.codename.strip(),
        purpose=payload.purpose.strip(),
        authorization_note=payload.authorization_note.strip(),
        prohibited_uses=payload.prohibited_uses.strip(),
        target_platforms=payload.target_platforms,
        provider_id=payload.provider_id,
        owner_id=user.id,
    )
    db.add(project)
    db.flush()
    _audit(db, project.id, "project.create", user, {"name": project.name})
    db.commit()
    db.refresh(project)
    return project_out(db, project)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return project_out(db, _owned(db, project_id, user))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = _owned(db, project_id, user)
    data = payload.model_dump(exclude_unset=True)
    if data.get("provider_id"):
        provider = db.get(Provider, data["provider_id"])
        if not provider or (settings.multiuser and provider.owner_id != user.id):
            raise HTTPException(status_code=400, detail="指定的模型配置不存在")
    for key, value in data.items():
        setattr(project, key, value)
    db.add(project)
    _audit(db, project.id, "project.update", user, {"fields": list(data.keys())})
    db.commit()
    db.refresh(project)
    return project_out(db, project)


@router.delete("/{project_id}", status_code=204)
def archive_project(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project = _owned(db, project_id, user)
    project.deleted_at = utcnow()
    project.status = "archived"
    db.add(project)
    _audit(db, project.id, "project.archive", user, {})
    db.commit()
    return None


@router.get("/{project_id}/persona", response_model=PersonaOut)
def get_persona(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project = _owned(db, project_id, user)
    claims = db.scalars(select(Claim).where(Claim.project_id == project_id)).all()
    approved = [claim for claim in claims if claim.status == "approved"]
    pending = [claim for claim in claims if claim.status == "proposed"]
    conflicts = db.scalars(
        select(Conflict).where(Conflict.project_id == project_id, Conflict.status == "open")
    ).all()
    dimensions = []
    for dimension, label in DIMENSION_LABELS.items():
        all_items = [claim for claim in claims if claim.dimension == dimension]
        approved_items = [claim for claim in all_items if claim.status == "approved"]
        dimensions.append(
            PersonaDimensionOut(
                dimension=dimension,
                label=label,
                total=len(all_items),
                approved=len(approved_items),
                statement_samples=[claim.statement for claim in approved_items[:4]],
                evidence_count=sum(claim.source_count for claim in approved_items),
            )
        )
    summary = (
        f"已批准 {len(approved)} 条断言，覆盖 {sum(1 for item in dimensions if item.approved)} 个维度；"
        f"待审核 {len(pending)} 条，开放冲突 {len(conflicts)} 条。"
    )
    return PersonaOut(
        project_id=project.id,
        project_name=project.codename or project.name,
        summary=summary,
        dimensions=dimensions,
        approved_claims=len(approved),
        pending_claims=len(pending),
        conflicts_open=len(conflicts),
    )


@router.get("/{project_id}/audit")
def get_audit(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    limit: int = 100,
):
    _owned(db, project_id, user)
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.project_id == project_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(min(limit, 500))
    ).all()
    return [
        {
            "id": event.id,
            "action": event.action,
            "actor": event.actor,
            "detail": event.detail,
            "created_at": event.created_at,
        }
        for event in events
    ]