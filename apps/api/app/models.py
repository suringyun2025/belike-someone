from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    # Local single-user app: store local naive timestamps so the UI and exports
    # display the same wall-clock time without timezone conversion surprises.
    return datetime.now()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:14]}"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prj"))
    name: Mapped[str] = mapped_column(String(200))
    codename: Mapped[str] = mapped_column(String(200), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    authorization_note: Mapped[str] = mapped_column(Text, default="")
    prohibited_uses: Mapped[str] = mapped_column(Text, default="")
    target_platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="active")
    provider_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("providers.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sources: Mapped[list[Source]] = relationship(back_populates="project", cascade="all, delete-orphan")
    claims: Mapped[list[Claim]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[list[Job]] = relationship(back_populates="project", cascade="all, delete-orphan")
    skills: Mapped[list[Skill]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("src"))
    project_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(40), default="document")
    license_note: Mapped[str] = mapped_column(Text, default="")
    consent_scope: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="uploaded", index=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    redaction_count: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="sources")
    documents: Mapped[list[Document]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    chunks: Mapped[list[Chunk]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("doc"))
    source_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    parser: Mapped[str] = mapped_column(String(80), default="builtin")
    parser_version: Mapped[str] = mapped_column(String(40), default="1")
    language: Mapped[str] = mapped_column(String(20), default="zh")
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source: Mapped[Source] = relationship(back_populates="documents")
    blocks: Mapped[list[DocumentBlock]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentBlock.order_index"
    )
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentBlock(Base):
    __tablename__ = "document_blocks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("blk"))
    document_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40), default="paragraph")
    heading: Mapped[str] = mapped_column(String(500), default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_char: Mapped[int] = mapped_column(Integer, default=0)
    end_char: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="blocks")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("chk"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    heading_path: Mapped[str] = mapped_column(String(1000), default="")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_char: Mapped[int] = mapped_column(Integer, default=0)
    end_char: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source: Mapped[Source] = relationship(back_populates="chunks")
    document: Mapped[Document] = relationship(back_populates="chunks")


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("emb"))
    chunk_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(200))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prv"))
    name: Mapped[str] = mapped_column(String(200))
    protocol: Mapped[str] = mapped_column(String(40), index=True)
    base_url: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(300))
    api_version: Mapped[str] = mapped_column(String(80), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_test_status: Mapped[str] = mapped_column(String(40), default="untested")
    last_test_error: Mapped[str] = mapped_column(Text, default="")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("clm"))
    project_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    dimension: Mapped[str] = mapped_column(String(40), index=True)
    statement: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(60), default="observed_pattern")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence_grade: Mapped[str] = mapped_column(String(60), default="model_inference")
    status: Mapped[str] = mapped_column(String(40), default="proposed", index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    review_reason: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    project: Mapped[Project] = relationship(back_populates="claims")
    evidence: Mapped[list[EvidenceItem]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evd"))
    claim_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[str] = mapped_column(String(40), index=True)
    quote: Mapped[str] = mapped_column(Text)
    start_char: Mapped[int] = mapped_column(Integer, default=0)
    end_char: Mapped[int] = mapped_column(Integer, default=0)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading: Mapped[str] = mapped_column(String(500), default="")
    evidence_type: Mapped[str] = mapped_column(String(60), default="direct_quote")
    strength: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="evidence")


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cfl"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    claim_a_id: Mapped[str] = mapped_column(String(40), index=True)
    claim_b_id: Mapped[str] = mapped_column(String(40), index=True)
    conflict_type: Mapped[str] = mapped_column(String(60), default="potential")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    resolution: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    project_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="distill")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    current_stage: Mapped[str] = mapped_column(String(80), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lease fields implement atomic multi-worker claiming. A worker that dies
    # leaves an expired lease behind, and another replica reclaims the job.
    worker_id: Mapped[str] = mapped_column(String(120), default="")
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Fencing token: incremented on every claim. A stalled worker whose job was
    # reclaimed holds a stale epoch and must not write results any more.
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    # Aggregated provider usage; never used to bill the user, only to show cost.
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    project: Mapped[Project] = relationship(back_populates="jobs")
    stages: Mapped[list[StageRun]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="StageRun.created_at"
    )


class StageRun(Base):
    __tablename__ = "stage_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("stg"))
    job_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship(back_populates="stages")


class Skill(TimestampMixin, Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("skl"))
    project_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    dimension: Mapped[str] = mapped_column(String(40), default="professional")
    status: Mapped[str] = mapped_column(String(40), default="compiled", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text, default="")
    files: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    project: Mapped[Project] = relationship(back_populates="skills")


class EvalCase(TimestampMixin, Base):
    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evc"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    skill_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(60), default="positive")
    prompt: Mapped[str] = mapped_column(Text)
    expected: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evr"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    skill_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("exp"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="completed")
    path: Mapped[str] = mapped_column(Text)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("aud"))
    project_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    actor: Mapped[str] = mapped_column(String(120), default="local-user")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SkillVersion(Base):
    """Immutable snapshot of a compiled Skill, enabling diff and rollback.

    ``Skill`` keeps the current version; this table keeps the history so a
    reviewer can compare v3 against v4 and see which claims changed.
    """

    __tablename__ = "skill_versions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("skv"))
    skill_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("skills.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text, default="")
    files: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    job_id: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_skill_versions_skill_version", "skill_id", "version"),)


Index("ix_claims_project_dimension", Claim.project_id, Claim.dimension)
Index("ix_evidence_claim", EvidenceItem.claim_id)
