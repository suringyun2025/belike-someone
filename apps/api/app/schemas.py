from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Protocol = Literal["openai_responses", "openai_chat", "anthropic", "gemini"]
Dimension = Literal["professional", "decision", "workflow", "style", "boundary", "knowledge"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    codename: str = ""
    purpose: str = ""
    authorization_note: str = ""
    prohibited_uses: str = ""
    target_platforms: list[str] = []
    provider_id: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    codename: str | None = None
    purpose: str | None = None
    authorization_note: str | None = None
    prohibited_uses: str | None = None
    target_platforms: list[str] | None = None
    provider_id: str | None = None
    status: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    codename: str
    purpose: str
    authorization_note: str
    prohibited_uses: str
    target_platforms: list[str]
    status: str
    provider_id: str | None
    created_at: datetime
    updated_at: datetime
    source_count: int = 0
    claim_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    pending_count: int = 0
    skill_count: int = 0
    latest_job_id: str | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    filename: str
    original_name: str
    mime: str
    size: int
    sha256: str
    source_type: str
    status: str
    duplicate_of: str | None
    parse_error: str | None
    redaction_count: int
    meta: dict[str, Any]
    created_at: datetime
    chunk_count: int = 0


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    protocol: Protocol
    base_url: str
    model_id: str
    api_version: str = ""
    api_key: str = ""
    params: dict[str, Any] = {}
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = None
    protocol: Protocol | None = None
    base_url: str | None = None
    model_id: str | None = None
    api_version: str | None = None
    api_key: str | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None


class ProviderOut(BaseModel):
    id: str
    name: str
    protocol: str
    base_url: str
    model_id: str
    api_version: str
    has_api_key: bool
    api_key_mask: str
    params: dict[str, Any]
    capabilities: dict[str, Any]
    enabled: bool
    last_test_status: str
    last_test_error: str
    last_tested_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    stage: str
    status: str
    output: dict[str, Any]
    usage: dict[str, Any]
    error: str
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    kind: str
    status: str
    current_stage: str
    progress: int
    config: dict[str, Any]
    result: dict[str, Any]
    error: str
    pause_requested: bool
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    worker_id: str = ""
    usage: dict[str, Any] = {}
    stages: list[StageOut] = []


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    chunk_id: str
    source_id: str
    quote: str
    start_char: int
    end_char: int
    page: int | None
    heading: str
    evidence_type: str
    strength: float


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    dimension: str
    statement: str
    claim_type: str
    confidence: float
    evidence_grade: str
    status: str
    source_count: int
    review_reason: str
    created_at: datetime
    evidence: list[EvidenceOut] = []


class ConflictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    claim_a_id: str
    claim_b_id: str
    conflict_type: str
    description: str
    status: str
    resolution: str
    created_at: datetime


class BulkReviewRequest(BaseModel):
    claim_ids: list[str] = []
    status: Literal["approved", "rejected", "proposed"]
    reason: str = ""


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    name: str
    title: str
    description: str
    dimension: str
    status: str
    version: int
    content: str
    files: dict[str, Any]
    validation: dict[str, Any]
    claim_ids: list[str]
    created_at: datetime
    updated_at: datetime


class EvalCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    skill_id: str | None
    category: str
    prompt: str
    expected: str
    meta: dict[str, Any]


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    skill_id: str
    status: str
    results: dict[str, Any]
    report: str
    created_at: datetime
    finished_at: datetime | None


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    status: str
    path: str
    manifest: dict[str, Any]
    created_at: datetime


class PersonaDimensionOut(BaseModel):
    dimension: str
    label: str
    total: int
    approved: int
    statement_samples: list[str]
    evidence_count: int


class PersonaOut(BaseModel):
    project_id: str
    project_name: str
    summary: str
    dimensions: list[PersonaDimensionOut]
    approved_claims: int
    pending_claims: int
    conflicts_open: int


class DashboardOut(BaseModel):
    projects: int
    sources: int
    claims_pending: int
    skills: int
    jobs_running: int
    jobs_failed: int
    recent_projects: list[dict[str, Any]]
    recent_jobs: list[dict[str, Any]]


class HealthOut(BaseModel):
    status: str
    version: str
    database: str


class SettingsOut(BaseModel):
    data_dir: str
    export_dir: str
    database_url: str
    inline_worker: bool
    chunk_chars: int
    chunk_overlap: int
    max_chunks_per_job: int
    max_upload_mb: int


class DemoOut(BaseModel):
    project_id: str
    name: str
    source_id: str
    message: str


class JobCreate(BaseModel):
    kind: Literal["distill", "compile"] = "distill"
    provider_id: str | None = None
    run_llm_evals: bool = False


class ConflictPatch(BaseModel):
    status: Literal["open", "resolved", "ignored"] = "resolved"
    resolution: str = ""


class EvaluateRequest(BaseModel):
    provider_id: str | None = None
    judge_provider_id: str | None = None
    max_cases: int = 10


class ProviderTestOut(BaseModel):
    ok: bool
    latency_ms: int
    text: str = ""
    model: str = ""
    warnings: list[str] = []
    error_code: str = ""
    error_message: str = ""


class ClaimPatch(BaseModel):
    status: Literal["approved", "rejected", "proposed"] | None = None
    statement: str | None = None
    review_reason: str | None = None
    dimension: Dimension | None = None

    @field_validator("statement")
    @classmethod
    def statement_not_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("statement 不能为空")
        return value
