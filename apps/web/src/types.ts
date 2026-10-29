export type JobStatus =
  | "queued"
  | "running"
  | "waiting_for_review"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type Protocol = "openai_responses" | "openai_chat" | "anthropic" | "gemini";
export type Dimension =
  | "professional"
  | "decision"
  | "workflow"
  | "style"
  | "boundary"
  | "knowledge";

export interface Project {
  id: string;
  name: string;
  codename: string;
  purpose: string;
  authorization_note: string;
  prohibited_uses: string;
  target_platforms: string[];
  status: string;
  provider_id: string | null;
  created_at: string;
  updated_at: string;
  source_count: number;
  claim_count: number;
  approved_count: number;
  rejected_count: number;
  pending_count: number;
  skill_count: number;
  latest_job_id: string | null;
}

export interface Source {
  id: string;
  project_id: string;
  filename: string;
  original_name: string;
  mime: string;
  size: number;
  sha256: string;
  source_type: string;
  status: string;
  duplicate_of: string | null;
  parse_error: string | null;
  redaction_count: number;
  meta: Record<string, unknown>;
  created_at: string;
  chunk_count: number;
}

export interface Block {
  id: string;
  order_index: number;
  text: string;
  kind: string;
  heading: string;
  page: number | null;
  start_char: number;
  end_char: number;
  meta: Record<string, unknown>;
}

export interface Chunk {
  id: string;
  order_index: number;
  text: string;
  token_estimate: number;
  heading_path: string;
  page_start: number | null;
  page_end: number | null;
  start_char: number;
  end_char: number;
  excluded: boolean;
  sha256: string;
}

export interface Provider {
  id: string;
  name: string;
  protocol: Protocol;
  base_url: string;
  model_id: string;
  api_version: string;
  has_api_key: boolean;
  api_key_mask: string;
  params: Record<string, unknown>;
  capabilities: Record<string, unknown>;
  enabled: boolean;
  last_test_status: string;
  last_test_error: string;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Stage {
  id: string;
  stage: string;
  status: string;
  output: Record<string, unknown>;
  usage: Record<string, unknown>;
  error: string;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface Job {
  id: string;
  project_id: string;
  kind: "distill" | "compile";
  status: JobStatus;
  current_stage: string;
  progress: number;
  config: Record<string, unknown>;
  result: Record<string, any>;
  error: string;
  pause_requested: boolean;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  worker_id: string;
  usage: {
    totals?: Record<string, number>;
    by_model?: Record<string, Record<string, number>>;
  };
  stages: Stage[];
}

export interface Evidence {
  id: string;
  chunk_id: string;
  source_id: string;
  quote: string;
  start_char: number;
  end_char: number;
  page: number | null;
  heading: string;
  evidence_type: string;
  strength: number;
}

export interface Claim {
  id: string;
  project_id: string;
  dimension: Dimension;
  statement: string;
  claim_type: string;
  confidence: number;
  evidence_grade: string;
  status: "proposed" | "approved" | "rejected";
  source_count: number;
  review_reason: string;
  created_at: string;
  evidence: Evidence[];
}

export interface Conflict {
  id: string;
  project_id: string;
  claim_a_id: string;
  claim_b_id: string;
  conflict_type: string;
  description: string;
  status: string;
  resolution: string;
  created_at: string;
}

export interface Skill {
  id: string;
  project_id: string;
  name: string;
  title: string;
  description: string;
  dimension: Dimension;
  status: string;
  version: number;
  content: string;
  files: Record<string, string>;
  validation: Record<string, any>;
  claim_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface EvalCase {
  id: string;
  project_id: string;
  skill_id: string | null;
  category: string;
  prompt: string;
  expected: string;
  meta: Record<string, unknown>;
}

export interface EvalRun {
  id: string;
  project_id: string;
  skill_id: string;
  status: string;
  results: Record<string, any>;
  report: string;
  created_at: string;
  finished_at: string | null;
}

export interface Export {
  id: string;
  project_id: string;
  status: string;
  path: string;
  manifest: Record<string, any>;
  created_at: string;
}

export interface PersonaDimension {
  dimension: Dimension;
  label: string;
  total: number;
  approved: number;
  statement_samples: string[];
  evidence_count: number;
}

export interface Persona {
  project_id: string;
  project_name: string;
  summary: string;
  dimensions: PersonaDimension[];
  approved_claims: number;
  pending_claims: number;
  conflicts_open: number;
}

export interface Dashboard {
  projects: number;
  sources: number;
  claims_pending: number;
  skills: number;
  jobs_running: number;
  jobs_failed: number;
  recent_projects: Project[];
  recent_jobs: Array<{
    id: string;
    project_id: string;
    kind: string;
    status: JobStatus;
    current_stage: string;
    progress: number;
    created_at: string;
  }>;
}

export interface Meta {
  version: string;
  env: string;
  dimensions: Array<{ value: Dimension; label: string }>;
  protocols: Array<{
    value: Protocol;
    label: string;
    capabilities: Record<string, any>;
  }>;
  skill_spec: {
    name_max: number;
    description_max: number;
    compatibility_max: number;
    validator: string;
  };
}

export interface Settings {
  data_dir: string;
  export_dir: string;
  database_url: string;
  inline_worker: boolean;
  chunk_chars: number;
  chunk_overlap: number;
  max_chunks_per_job: number;
  max_upload_mb: number;
}

export interface DemoResult {
  project_id: string;
  name: string;
  source_id: string;
  message: string;
}

export interface SearchResult {
  chunk_id: string;
  project_id: string;
  source_id: string;
  source_name: string;
  text: string;
  heading_path: string;
  page_start: number | null;
  page_end: number | null;
  score: number | null;
  mode: string;
}

export interface SearchResponse {
  query: string;
  mode: string;
  results: SearchResult[];
  warning: string;
}

export interface VectorStatus {
  chunks: number;
  embedded: number;
  model: string;
  backend: string;
  dim: number;
  vec: boolean;
  warning: string;
  has_chunks: boolean;
}

export interface ProviderTestResult {
  ok: boolean;
  latency_ms: number;
  text: string;
  model: string;
  warnings: string[];
  error_code: string;
  error_message: string;
}


export interface SkillVersionInfo {
  id: string;
  version: number;
  content_hash: string;
  claim_ids: string[];
  job_id: string;
  created_at: string;
  lines: number;
}

export interface SkillDiff {
  skill: string;
  from: number;
  to: number;
  added_lines: number;
  removed_lines: number;
  claims_added: string[];
  claims_removed: string[];
  diff: string;
}

export interface UsageBreakdown {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface UsageOverview {
  totals: UsageBreakdown;
  projects: Array<
    UsageBreakdown & {
      project_id: string;
      project_name: string;
      jobs: number;
      models: Record<string, UsageBreakdown>;
    }
  >;
  note: string;
}

export interface RuntimeStats {
  projects: number;
  sources: number;
  skills: number;
  providers: number;
  jobs: number;
  jobs_active: number;
  runtime: {
    version: string;
    env: string;
    database: string;
    inline_worker: boolean;
    worker_id: string;
    lease_seconds: number;
  };
}

export interface ReadyCheck {
  status: string;
  version: string;
  checks: Record<string, any>;
}
