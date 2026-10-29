from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Chunk,
    Claim,
    Job,
    Project,
    Provider,
    Skill,
    Source,
    utcnow,
)
from ..schemas import (
    ClaimOut,
    JobOut,
    ProjectOut,
    ProviderOut,
    SourceOut,
    StageOut,
)


def project_out(db: Session, project: Project) -> ProjectOut:
    source_count = db.scalar(
        select(func.count()).select_from(Source).where(Source.project_id == project.id)
    ) or 0
    claim_count = db.scalar(
        select(func.count()).select_from(Claim).where(Claim.project_id == project.id)
    ) or 0
    approved_count = db.scalar(
        select(func.count())
        .select_from(Claim)
        .where(Claim.project_id == project.id, Claim.status == "approved")
    ) or 0
    rejected_count = db.scalar(
        select(func.count())
        .select_from(Claim)
        .where(Claim.project_id == project.id, Claim.status == "rejected")
    ) or 0
    skill_count = db.scalar(
        select(func.count()).select_from(Skill).where(Skill.project_id == project.id)
    ) or 0
    latest_job = db.scalar(
        select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc()).limit(1)
    )
    return ProjectOut(
        id=project.id,
        name=project.name,
        codename=project.codename,
        purpose=project.purpose,
        authorization_note=project.authorization_note,
        prohibited_uses=project.prohibited_uses,
        target_platforms=project.target_platforms or [],
        status=project.status,
        provider_id=project.provider_id,
        created_at=project.created_at,
        updated_at=project.updated_at,
        source_count=source_count,
        claim_count=claim_count,
        approved_count=approved_count,
        # Badges must not be derived as `claim_count - approved_count`: that
        # arithmetic silently counts rejected claims as pending review.
        rejected_count=rejected_count,
        pending_count=max(0, claim_count - approved_count - rejected_count),
        skill_count=skill_count,
        latest_job_id=latest_job.id if latest_job else None,
    )


def source_out(db: Session, source: Source) -> SourceOut:
    chunk_count = db.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.source_id == source.id)
    ) or 0
    return SourceOut(
        id=source.id,
        project_id=source.project_id,
        filename=source.filename,
        original_name=source.original_name,
        mime=source.mime,
        size=source.size,
        sha256=source.sha256,
        source_type=source.source_type,
        status=source.status,
        duplicate_of=source.duplicate_of,
        parse_error=source.parse_error,
        redaction_count=source.redaction_count,
        meta=source.meta or {},
        created_at=source.created_at,
        chunk_count=chunk_count,
    )


def provider_out(provider: Provider) -> ProviderOut:
    return ProviderOut(
        id=provider.id,
        name=provider.name,
        protocol=provider.protocol,
        base_url=provider.base_url,
        model_id=provider.model_id,
        api_version=provider.api_version,
        has_api_key=bool(provider.api_key_encrypted),
        api_key_mask="已配置" if provider.api_key_encrypted else "",
        params=provider.params or {},
        capabilities=provider.capabilities or {},
        enabled=provider.enabled,
        last_test_status=provider.last_test_status,
        last_test_error=provider.last_test_error,
        last_tested_at=provider.last_tested_at,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def job_out(job: Job) -> JobOut:
    stages = [
        StageOut(
            id=stage.id,
            stage=stage.stage,
            status=stage.status,
            output=stage.output or {},
            usage=stage.usage or {},
            error=stage.error,
            attempt=stage.attempt,
            started_at=stage.started_at,
            finished_at=stage.finished_at,
        )
        for stage in sorted(job.stages, key=lambda item: item.created_at or utcnow())
    ]
    return JobOut(
        id=job.id,
        project_id=job.project_id,
        kind=job.kind,
        status=job.status,
        current_stage=job.current_stage,
        progress=job.progress,
        config=job.config or {},
        result=job.result or {},
        error=job.error,
        pause_requested=job.pause_requested,
        cancel_requested=job.cancel_requested,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        worker_id=job.worker_id or "",
        usage=job.usage or {},
        stages=stages,
    )


def claim_out(claim: Claim) -> ClaimOut:
    return ClaimOut(
        id=claim.id,
        project_id=claim.project_id,
        dimension=claim.dimension,
        statement=claim.statement,
        claim_type=claim.claim_type,
        confidence=claim.confidence,
        evidence_grade=claim.evidence_grade,
        status=claim.status,
        source_count=claim.source_count,
        review_reason=claim.review_reason,
        created_at=claim.created_at,
        evidence=[
            {
                "id": evidence.id,
                "chunk_id": evidence.chunk_id,
                "source_id": evidence.source_id,
                "quote": evidence.quote,
                "start_char": evidence.start_char,
                "end_char": evidence.end_char,
                "page": evidence.page,
                "heading": evidence.heading,
                "evidence_type": evidence.evidence_type,
                "strength": evidence.strength,
            }
            for evidence in claim.evidence
        ],
    )
