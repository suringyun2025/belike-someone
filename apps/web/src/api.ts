import type {
  Claim,
  Conflict,
  Dashboard,
  DemoResult,
  EvalCase,
  EvalRun,
  Export,
  Job,
  Meta,
  Persona,
  Project,
  Provider,
  ProviderTestResult,
  ReadyCheck,
  RuntimeStats,
  SearchResponse,
  Settings,
  Skill,
  SkillDiff,
  SkillVersionInfo,
  Source,
  UsageOverview,
  VectorStatus,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  code: string;
  requestId: string;
  retryable: boolean;
  constructor(
    message: string,
    status: number,
    detail?: unknown,
    code = "",
    requestId = "",
    retryable = false,
  ) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.requestId = requestId;
    this.retryable = retryable;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("content-type", "application/json");
  }
  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let payload: any = null;
    try {
      payload = await response.json();
    } catch {
      payload = await response.text();
    }
    // The backend now returns {detail, error:{code,message,request_id}}, but
    // keep accepting a bare string so older responses still render sensibly.
    const structured =
      payload && typeof payload === "object" && payload.error && typeof payload.error === "object"
        ? payload.error
        : null;
    const message =
      structured?.message ||
      (payload && typeof payload === "object" && (payload.detail || payload.message)) ||
      `请求失败（HTTP ${response.status}）`;
    throw new ApiError(
      String(message),
      response.status,
      payload,
      structured?.code || "",
      structured?.request_id || response.headers.get("x-request-id") || "",
      response.status === 429 || response.status >= 500,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  health: () => request<{ status: string; version: string; database: string }>("/health"),
  ready: () => request<ReadyCheck>("/ready"),
  stats: () => request<RuntimeStats>("/stats"),
  usage: () => request<UsageOverview>("/usage"),
  dashboard: () => request<Dashboard>("/dashboard"),
  createDemo: () => request<DemoResult>("/demo", { method: "POST" }),
  meta: () => request<Meta>("/meta"),
  settings: () => request<Settings>("/settings"),

  projects: () => request<Project[]>("/projects"),
  project: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (body: Partial<Project>) =>
    request<Project>("/projects", { method: "POST", body: json(body) }),
  updateProject: (id: string, body: Partial<Project>) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: json(body) }),
  archiveProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  persona: (id: string) => request<Persona>(`/projects/${id}/persona`),
  search: (id: string, q: string, limit = 8) =>
    request<SearchResponse>(`/projects/${id}/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  indexProject: (id: string, force = false) =>
    request<{ indexed: number; remaining: number; model: string; backend: string; vec: boolean; warning: string }>(
      `/projects/${id}/index?force=${force ? "true" : "false"}`,
      { method: "POST" },
    ),
  vectorStatus: (id: string) => request<VectorStatus>(`/projects/${id}/vector-status`),
  audit: (id: string) =>
    request<Array<{ id: string; action: string; actor: string; detail: any; created_at: string }>>(
      `/projects/${id}/audit`,
    ),

  sources: (projectId: string) => request<Source[]>(`/projects/${projectId}/sources`),
  uploadSources: (projectId: string, files: FileList | File[]) => {
    const data = new FormData();
    Array.from(files).forEach((file) => data.append("files", file));
    return request<Source[]>(`/projects/${projectId}/sources`, { method: "POST", body: data });
  },
  previewSource: (sourceId: string) =>
    request<{ source: Source; blocks: any[]; truncated: boolean }>(`/sources/${sourceId}/preview`),
  sourceChunks: (sourceId: string) => request<any[]>(`/sources/${sourceId}/chunks`),
  reparseSource: (sourceId: string) =>
    request<Source>(`/sources/${sourceId}/parse`, { method: "POST" }),
  deleteSource: (sourceId: string) => request<void>(`/sources/${sourceId}`, { method: "DELETE" }),

  providers: () => request<Provider[]>("/providers"),
  createProvider: (body: Record<string, unknown>) =>
    request<Provider>("/providers", { method: "POST", body: json(body) }),
  updateProvider: (id: string, body: Record<string, unknown>) =>
    request<Provider>(`/providers/${id}`, { method: "PATCH", body: json(body) }),
  deleteProvider: (id: string) => request<void>(`/providers/${id}`, { method: "DELETE" }),
  testProvider: (id: string, jsonMode = false) =>
    request<ProviderTestResult>(`/providers/${id}/test`, {
      method: "POST",
      body: json({ json_mode: jsonMode }),
    }),

  jobs: (projectId: string) => request<Job[]>(`/projects/${projectId}/jobs`),
  job: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  createJob: (projectId: string, body: { kind: "distill" | "compile"; provider_id?: string | null; run_llm_evals?: boolean }) =>
    request<Job>(`/projects/${projectId}/jobs`, { method: "POST", body: json(body) }),
  pauseJob: (jobId: string) => request<Job>(`/jobs/${jobId}/pause`, { method: "POST" }),
  resumeJob: (jobId: string) => request<Job>(`/jobs/${jobId}/resume`, { method: "POST" }),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  retryJob: (jobId: string) => request<Job>(`/jobs/${jobId}/retry`, { method: "POST" }),

  claims: (projectId: string, params?: { status?: string; dimension?: string }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.dimension) query.set("dimension", params.dimension);
    return request<Claim[]>(`/projects/${projectId}/claims${query.size ? `?${query}` : ""}`);
  },
  updateClaim: (claimId: string, body: { status?: string; statement?: string; dimension?: string; review_reason?: string }) =>
    request<Claim>(`/claims/${claimId}`, { method: "PATCH", body: json(body) }),
  bulkReview: (projectId: string, claimIds: string[], status: string, reason = "") =>
    request<{ updated: number; status: string }>(`/projects/${projectId}/claims/bulk-review`, {
      method: "POST",
      body: json({ claim_ids: claimIds, status, reason }),
    }),
  conflicts: (projectId: string) => request<Conflict[]>(`/projects/${projectId}/conflicts`),
  updateConflict: (conflictId: string, body: { status: string; resolution?: string }) =>
    request<Conflict>(`/conflicts/${conflictId}`, { method: "PATCH", body: json(body) }),

  skills: (projectId: string) => request<Skill[]>(`/projects/${projectId}/skills`),
  skill: (skillId: string) => request<Skill>(`/skills/${skillId}`),
  validateSkill: (skillId: string) =>
    request<{ ok: boolean; errors: string[]; warnings: string[] }>(`/skills/${skillId}/validate`, { method: "POST" }),
  evaluateSkill: (
    skillId: string,
    body?: { provider_id?: string | null; judge_provider_id?: string | null; max_cases?: number },
  ) => request<EvalRun>(`/skills/${skillId}/evaluate`, { method: "POST", body: json(body || {}) }),
  evalCases: (projectId: string) => request<EvalCase[]>(`/projects/${projectId}/eval-cases`),
  evalRuns: (projectId: string) => request<EvalRun[]>(`/projects/${projectId}/eval-runs`),

  skillVersions: (skillId: string) => request<SkillVersionInfo[]>(`/skills/${skillId}/versions`),
  skillDiff: (skillId: string, from: number, to: number) =>
    request<SkillDiff>(`/skills/${skillId}/diff?from_version=${from}&to_version=${to}`),
  setChunkExcluded: (chunkId: string, excluded: boolean) =>
    request<{ id: string; excluded: boolean }>(`/chunks/${chunkId}`, {
      method: "PATCH",
      body: json({ excluded }),
    }),

  exports: (projectId: string) => request<Export[]>(`/projects/${projectId}/exports`),
  exportDownloadUrl: (exportId: string) => `${BASE}/exports/${exportId}/download`,
};
