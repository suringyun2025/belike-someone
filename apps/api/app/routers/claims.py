from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user, owned_project
from ..models import AuditEvent, Claim, Conflict, Project, User
from ..schemas import BulkReviewRequest, ClaimOut, ClaimPatch, ConflictOut, ConflictPatch
from .common import claim_out

router = APIRouter(tags=["claims"])


def _get_project(db: Session, project_id: str, user: User) -> Project:
    return owned_project(project_id, db, user)


def _get_claim(db: Session, claim_id: str, user: User) -> Claim:
    """Resolve a claim and verify its project belongs to the caller."""
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="断言不存在")
    owned_project(claim.project_id, db, user)
    return claim


@router.get("/projects/{project_id}/claims", response_model=list[ClaimOut])
def list_claims(
    project_id: str,
    status: str | None = None,
    dimension: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _get_project(db, project_id, user)
    query = (
        select(Claim)
        .where(Claim.project_id == project_id)
        .options(selectinload(Claim.evidence))
        .order_by(Claim.dimension, Claim.created_at.desc())
        .limit(500)
    )
    if status:
        query = query.where(Claim.status == status)
    if dimension:
        query = query.where(Claim.dimension == dimension)
    claims = db.scalars(query).all()
    return [claim_out(claim) for claim in claims]


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(
    claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    claim = db.scalar(
        select(Claim).where(Claim.id == claim_id).options(selectinload(Claim.evidence))
    )
    if not claim:
        raise HTTPException(status_code=404, detail="断言不存在")
    owned_project(claim.project_id, db, user)
    return claim_out(claim)


@router.patch("/claims/{claim_id}", response_model=ClaimOut)
def update_claim(
    claim_id: str,
    payload: ClaimPatch,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    claim = db.scalar(
        select(Claim).where(Claim.id == claim_id).options(selectinload(Claim.evidence))
    )
    if not claim:
        raise HTTPException(status_code=404, detail="断言不存在")
    owned_project(claim.project_id, db, user)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(claim, key, value)
    db.add(claim)
    db.add(
        AuditEvent(
            project_id=claim.project_id,
            action="claim.review",
            detail={"claim_id": claim.id, "changes": data},
        )
    )
    db.commit()
    db.refresh(claim)
    return claim_out(claim)


@router.post("/projects/{project_id}/claims/bulk-review")
def bulk_review(
    project_id: str,
    payload: BulkReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _get_project(db, project_id, user)
    claims = db.scalars(
        select(Claim).where(
            Claim.project_id == project_id, Claim.id.in_(payload.claim_ids)
        )
    ).all() if payload.claim_ids else []
    if not claims and payload.claim_ids:
        raise HTTPException(status_code=404, detail="没有找到指定断言")
    for claim in claims:
        claim.status = payload.status
        if payload.reason:
            claim.review_reason = payload.reason
        db.add(claim)
    db.add(
        AuditEvent(
            project_id=project_id,
            action="claim.bulk_review",
            detail={"status": payload.status, "count": len(claims), "reason": payload.reason},
        )
    )
    db.commit()
    return {"updated": len(claims), "status": payload.status}


@router.get("/projects/{project_id}/conflicts", response_model=list[ConflictOut])
def list_conflicts(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    _get_project(db, project_id, user)
    conflicts = db.scalars(
        select(Conflict)
        .where(Conflict.project_id == project_id)
        .order_by(Conflict.created_at.desc())
        .limit(200)
    ).all()
    return [ConflictOut.model_validate(conflict) for conflict in conflicts]


@router.patch("/conflicts/{conflict_id}", response_model=ConflictOut)
def update_conflict(
    conflict_id: str,
    payload: ConflictPatch,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    conflict = db.get(Conflict, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="冲突不存在")
    owned_project(conflict.project_id, db, user)
    conflict.status = payload.status
    conflict.resolution = payload.resolution
    db.add(conflict)
    db.add(
        AuditEvent(
            project_id=conflict.project_id,
            action="conflict.review",
            detail={"conflict_id": conflict.id, "status": conflict.status},
        )
    )
    db.commit()
    db.refresh(conflict)
    return ConflictOut.model_validate(conflict)
