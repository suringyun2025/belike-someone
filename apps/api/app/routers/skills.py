from __future__ import annotations

import difflib
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, owned_project
from ..judge import evaluate_cases
from ..llm import LLMError, get_adapter
from ..models import (
    AuditEvent,
    EvalCase,
    EvalRun,
    Project,
    Provider,
    Skill,
    SkillVersion,
    User,
    utcnow,
)
from ..rate_limit import heavy_limiter
from ..pipeline import validate_skill
from ..schemas import EvalCaseOut, EvalRunOut, EvaluateRequest, SkillOut

router = APIRouter(tags=["skills"])


def _get_skill(db: Session, skill_id: str, user: User) -> Skill:
    """Resolve a skill and verify ownership through its project."""
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    owned_project(skill.project_id, db, user)
    return skill


def _get_provider(db: Session, provider_id: str, user: User) -> Provider | None:
    provider = db.get(Provider, provider_id)
    if not provider:
        return None
    from ..config import settings

    if settings.multiuser and provider.owner_id != user.id:
        return None
    return provider


@router.get("/projects/{project_id}/skills", response_model=list[SkillOut])
def list_skills(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    owned_project(project_id, db, user)
    skills = db.scalars(
        select(Skill).where(Skill.project_id == project_id).order_by(Skill.dimension, Skill.updated_at.desc())
    ).all()
    return [SkillOut.model_validate(skill) for skill in skills]


@router.get("/skills/{skill_id}", response_model=SkillOut)
def get_skill(
    skill_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return SkillOut.model_validate(_get_skill(db, skill_id, user))


@router.get("/skills/{skill_id}/files/{file_path:path}", response_class=PlainTextResponse)
def get_skill_file(
    skill_id: str,
    file_path: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    skill = _get_skill(db, skill_id, user)
    files = skill.files or {}
    if file_path not in files:
        raise HTTPException(status_code=404, detail="文件不存在")
    return PlainTextResponse(str(files[file_path]), media_type="text/markdown; charset=utf-8")


@router.post("/skills/{skill_id}/validate")
def validate_skill_endpoint(
    skill_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    skill = _get_skill(db, skill_id, user)
    report = validate_skill(skill)
    skill.validation = {**(skill.validation or {}), "static": report}
    skill.status = "validated" if report["ok"] else "failed"
    db.add(skill)
    db.add(
        AuditEvent(
            project_id=skill.project_id,
            action="skill.validate",
            detail={"skill_id": skill.id, "ok": report["ok"]},
        )
    )
    db.commit()
    return report


@router.post("/skills/{skill_id}/evaluate", response_model=EvalRunOut)
def evaluate_skill(
    skill_id: str,
    payload: EvaluateRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    skill = _get_skill(db, skill_id, user)
    project = db.get(Project, skill.project_id)
    request = payload or EvaluateRequest()
    allowed, retry = heavy_limiter.take(f"eval:{user.id}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"评测请求过于频繁，请 {int(retry)} 秒后重试",
            headers={"Retry-After": str(int(retry) + 1)},
        )
    # Provider lookups are owner-scoped: passing someone else's provider id must
    # not trigger a paid request against their account.
    generator_provider = (
        _get_provider(db, request.provider_id, user)
        if request.provider_id
        else (_get_provider(db, project.provider_id, user) if project and project.provider_id else None)
    )
    judge_provider = (
        _get_provider(db, request.judge_provider_id, user)
        if request.judge_provider_id
        else generator_provider
    )
    if not generator_provider or not judge_provider:
        raise HTTPException(
            status_code=400,
            detail="LLM-as-judge 需要生成模型与评审模型；请先配置 Provider 并选择模型",
        )
    try:
        generator = get_adapter(generator_provider, owner_id=user.id)
        judge = get_adapter(judge_provider, owner_id=user.id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模型配置不可用：{exc}") from exc

    try:
        raw = json.loads((skill.files or {}).get("evals/evals.json") or "{}")
    except ValueError:
        raw = {}
    source_cases = raw.get("cases") or []
    cases = [
        {
            "case_id": case.get("id", f"case-{index}"),
            "category": str(case.get("category", "positive")),
            "prompt": str(case.get("prompt", "")),
            "expected": str(case.get("expected", "")),
        }
        for index, case in enumerate(source_cases[: max(1, min(request.max_cases, 30))])
    ]
    if not cases:
        raise HTTPException(status_code=400, detail="该 Skill 没有评测用例")
    for case in cases:
        existing = db.scalar(
            select(EvalCase).where(
                EvalCase.skill_id == skill.id, EvalCase.prompt == case["prompt"]
            )
        )
        if not existing:
            existing = EvalCase(
                project_id=skill.project_id,
                skill_id=skill.id,
                category=case["category"],
                prompt=case["prompt"],
                expected=case["expected"],
                meta={"case_id": case["case_id"]},
            )
            db.add(existing)
            db.flush()
    try:
        result = evaluate_cases(
            skill_name=skill.name,
            skill_content=skill.content,
            skill_description=skill.description,
            cases=cases,
            generator=generator,
            judge=judge,
            generator_model=f"{generator_provider.protocol}:{generator_provider.model_id}",
            judge_model=f"{judge_provider.protocol}:{judge_provider.model_id}",
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"评审模型失败：{exc.code}: {exc.message}") from exc
    metrics = result.get("metrics", {})
    report = (
        f"{skill.name} · LLM-as-judge {metrics.get('scored_cases', 0)}/{metrics.get('cases', 0)} 例 · "
        f"overall {metrics.get('overall_score')} · pass {metrics.get('pass_rate')} · "
        f"trigger {metrics.get('trigger_accuracy')}"
    )
    run = EvalRun(
        project_id=skill.project_id,
        skill_id=skill.id,
        status="completed",
        results=result,
        report=report,
        finished_at=utcnow(),
    )
    db.add(run)
    db.flush()
    skill.validation = {
        **(skill.validation or {}),
        "eval": {
            "run_id": run.id,
            "cases": len(cases),
            "mode": "llm-judge",
            "metrics": metrics,
        },
    }
    db.add(skill)
    db.add(
        AuditEvent(
            project_id=skill.project_id,
            action="skill.evaluate",
            detail={"skill_id": skill.id, "cases": len(cases), "mode": "llm-judge"},
        )
    )
    db.commit()
    db.refresh(run)
    return EvalRunOut.model_validate(run)


@router.get("/projects/{project_id}/eval-cases", response_model=list[EvalCaseOut])
def list_eval_cases(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    owned_project(project_id, db, user)
    cases = db.scalars(
        select(EvalCase).where(EvalCase.project_id == project_id).order_by(EvalCase.created_at.desc())
    ).all()
    return [EvalCaseOut.model_validate(case) for case in cases]


@router.get("/projects/{project_id}/eval-runs", response_model=list[EvalRunOut])
def list_eval_runs(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    owned_project(project_id, db, user)
    runs = db.scalars(
        select(EvalRun).where(EvalRun.project_id == project_id).order_by(EvalRun.created_at.desc())
    ).all()
    return [EvalRunOut.model_validate(run) for run in runs]


@router.get("/eval-runs/{run_id}", response_model=EvalRunOut)
def get_eval_run(
    run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    run = db.get(EvalRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    owned_project(run.project_id, db, user)
    return EvalRunOut.model_validate(run)


# --- version history -------------------------------------------------------


@router.get("/skills/{skill_id}/versions")
def list_skill_versions(
    skill_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    skill = _get_skill(db, skill_id, user)
    versions = db.scalars(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill.id)
        .order_by(SkillVersion.version.desc())
    ).all()
    return [
        {
            "id": version.id,
            "version": version.version,
            "content_hash": version.content_hash,
            "claim_ids": version.claim_ids or [],
            "job_id": version.job_id,
            "created_at": version.created_at,
            "lines": len((version.content or "").splitlines()),
        }
        for version in versions
    ]


@router.get("/skills/{skill_id}/diff")
def diff_skill_versions(
    skill_id: str,
    from_version: int,
    to_version: int,
    db: Session = Depends(get_db),
):
    """Unified diff between two compiled versions of the same Skill.

    Reviewers need to answer "what changed since the last approval", which a
    single mutable `content` column cannot express.
    """
    skill = _get_skill(db, skill_id)
    left = db.scalar(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill.id, SkillVersion.version == from_version
        )
    )
    right = db.scalar(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill.id, SkillVersion.version == to_version
        )
    )
    if not left or not right:
        raise HTTPException(status_code=404, detail="指定版本不存在")
    diff = difflib.unified_diff(
        (left.content or "").splitlines(),
        (right.content or "").splitlines(),
        fromfile=f"v{left.version}",
        tofile=f"v{right.version}",
        lineterm="",
        n=3,
    )
    added = sum(1 for line in difflib.ndiff(
        (left.content or "").splitlines(), (right.content or "").splitlines()
    ) if line.startswith("+ "))
    removed = sum(1 for line in difflib.ndiff(
        (left.content or "").splitlines(), (right.content or "").splitlines()
    ) if line.startswith("- "))
    return {
        "skill": skill.name,
        "from": left.version,
        "to": right.version,
        "added_lines": added,
        "removed_lines": removed,
        "claims_added": sorted(set(right.claim_ids or []) - set(left.claim_ids or [])),
        "claims_removed": sorted(set(left.claim_ids or []) - set(right.claim_ids or [])),
        "diff": "\n".join(diff),
    }
