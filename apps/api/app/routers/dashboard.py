from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..ingest import create_source_from_file
from ..models import AuditEvent, Claim, Job, Project, Skill, Source, User
from ..schemas import DashboardOut, DemoOut
from .common import project_out

router = APIRouter(tags=["dashboard"])

DEMO_NOTE = """# 示例：解决方案架构师的工作笔记

> 本文件是虚构示例，仅用于演示蒸馏流程，不对应任何真实人物。

## 决策方式

我通常先把硬约束写清楚，再比较性能、功耗、面积和成本。遇到公共 API 变更时，我会先检查兼容性，再补回归测试。
如果证据不足，我会把结论标成待验证，而不是直接下判断。我不喜欢在没有测量数据时做性能结论。
遇到多个候选方案时，我会先列出硬约束，再按性能、成本、风险和可逆性逐项权衡，最后给出回滚条件。
我通常把方案决策写成记录：上下文、备选方案、放弃理由和验证计划。
架构评审时，我优先关注数据一致性、故障隔离和可观测性。

## 工作流

我习惯先复现问题，再提出假设，然后设计最小实验，最后定位根因。
代码评审时，我先看风险，再看可维护性，最后才看风格。
交付前我会检查失败路径、回滚方案和监控指标。

## 专业标准

我的专业标准是：关键路径有测试、失败路径有回滚、线上行为有监控。

## 表达风格

我表达时尽量简洁直接，先给结论，再给依据。我会明确区分事实和推测，不用模糊措辞掩盖不确定性。
我倾向于用结构化列表说明权衡，而不是长篇铺垫。

## 边界

我不会冒充他人发表声明，也不讨论未经授权的隐私信息。
超出专业范围的问题，我会明确说明并建议咨询相应专家。

## 知识与案例

在分布式系统设计中，我会优先考虑幂等性、重试边界和可观测性。
我认为架构决策应该记录上下文、备选方案和放弃理由，便于后续复盘。
"""

DEMO_CHAT = """{"sender":"架构师","timestamp":"2026-03-02 10:12","content":"这个方案先别急着定。我们先把一致性要求和故障域写清楚，再比较成本。"}
{"sender":"同事","timestamp":"2026-03-02 10:14","content":"性能数据还没有，要不要先上线再看？"}
{"sender":"架构师","timestamp":"2026-03-02 10:15","content":"不行，没有测量数据就下性能结论风险太大。先做最小压测，拿到数据再决策。"}
{"sender":"同事","timestamp":"2026-03-02 10:17","content":"评审时你一般先看什么？"}
{"sender":"架构师","timestamp":"2026-03-02 10:18","content":"先看风险和失败路径，再看可维护性，最后才看风格。风格问题不值得阻塞发布。"}
{"sender":"同事","timestamp":"2026-03-02 10:20","content":"能不能用你的名义发个声明？"}
{"sender":"架构师","timestamp":"2026-03-02 10:21","content":"不行，我不会冒充任何人发表声明。可以做一份明确标注 AI 辅助的分析。"}
"""


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Aggregates for the landing page.

    Counts are scoped with a correlated ``EXISTS`` instead of ``IN (subquery)``
    inside ``select_from(model)``: the latter makes SQLAlchemy add the subquery's
    table as a second FROM element, yielding a cartesian product.
    """
    from sqlalchemy import exists

    multi = settings.multiuser
    project_filter: list = [Project.deleted_at.is_(None)]
    if multi:
        project_filter.append(Project.owner_id == user.id)
    projects = db.scalars(
        select(Project).where(*project_filter).order_by(Project.updated_at.desc()).limit(5)
    ).all()

    def _owned(model):
        condition = Project.id == model.project_id
        if multi:
            condition = condition & (Project.owner_id == user.id)
        return exists(select(Project.id).where(condition, Project.deleted_at.is_(None)))

    jobs_query = select(Job)
    if multi:
        jobs_query = jobs_query.where(_owned(Job))
    recent_jobs = db.scalars(jobs_query.order_by(Job.created_at.desc()).limit(6)).all()

    def _count(model, *where):
        stmt = select(func.count()).select_from(model)
        if where:
            stmt = stmt.where(*where)
        return db.scalar(stmt) or 0

    scope = [_owned] if multi else []

    return DashboardOut(
        projects=_count(Project, *project_filter),
        sources=_count(Source, *[f(Source) for f in scope]),
        claims_pending=_count(
            Claim, *[f(Claim) for f in scope], Claim.status == "proposed"
        ),
        skills=_count(Skill, *[f(Skill) for f in scope]),
        jobs_running=_count(
            Job, *[f(Job) for f in scope], Job.status.in_(["queued", "running", "paused"])
        ),
        jobs_failed=_count(Job, *[f(Job) for f in scope], Job.status == "failed"),
        recent_projects=[
            project_out(db, project).model_dump(mode="json") for project in projects
        ],
        recent_jobs=[
            {
                "id": job.id,
                "project_id": job.project_id,
                "kind": job.kind,
                "status": job.status,
                "current_stage": job.current_stage,
                "progress": job.progress,
                "created_at": job.created_at,
            }
            for job in recent_jobs
        ],
    )


@router.post("/demo", response_model=DemoOut, status_code=201)
def create_demo(db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = Project(
        owner_id=user.id,
        name="示例项目：解决方案架构师",
        codename="示例架构师",
        purpose="演示如何从工作笔记和聊天记录中蒸馏专业能力、决策方式与表达风格。",
        authorization_note="虚构示例资料，仅用于产品演示，不包含真实人物信息。",
        prohibited_uses="不得用于冒充真实人物、欺骗或未经授权的商业用途。",
        target_platforms=["Claude Code", "Cursor", "Qoder"],
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    source = create_source_from_file(
        db,
        project.id,
        "示例-架构师工作笔记.md",
        DEMO_NOTE.encode("utf-8"),
        source_type="document",
        parse_now=True,
    )
    create_source_from_file(
        db,
        project.id,
        "示例-评审对话.jsonl",
        DEMO_CHAT.encode("utf-8"),
        source_type="chat",
        parse_now=True,
    )
    db.add(
        AuditEvent(
            project_id=project.id,
            actor_id=user.id,
            actor=user.email,
            action="demo.create",
            detail={"source_id": source.id},
        )
    )
    db.commit()
    return DemoOut(
        project_id=project.id,
        name=project.name,
        source_id=source.id,
        message="示例项目已创建。点击“开始蒸馏”即可在离线启发式模式下运行。",
    )
