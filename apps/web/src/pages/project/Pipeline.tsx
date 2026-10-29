import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Circle,
  Clock,
  FlaskConical,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  Square,
  XCircle,
} from "lucide-react";
import { api } from "../../api";
import type { Job, JobStatus, Stage } from "../../types";
import type { ProjectTabProps } from "../ProjectWorkspace";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState,
  Progress,
  Select,
  StatusBadge,
  useToast,
} from "../../ui";
import { formatDate, relativeTime, truncate } from "../../lib/format";
import { stageLabels } from "../../lib/labels";
import { useJobStream } from "../../lib/hooks";

const DISTILL_STAGES = [
  "s01_intake",
  "s02_ingest",
  "s03_parse",
  "s04_normalize",
  "s05_chunk",
  "s06_corpus_map",
  "s07_extract",
  "s08_ground",
  "s09_conflicts",
  "s10_consolidate",
];
const COMPILE_STAGES = ["s11_compose", "s12_compile", "s13_validate", "s14_eval", "s15_package"];
const TERMINAL: JobStatus[] = ["completed", "failed", "cancelled", "waiting_for_review"];

export function PipelineTab({ project, providers, setTab }: ProjectTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [liveJob, setLiveJob] = useState<Job | null>(null);
  const [providerId, setProviderId] = useState(project.provider_id || "");
  const [runLlmEvals, setRunLlmEvals] = useState(false);
  const terminalRef = useRef("");

  const jobs = useQuery({
    queryKey: ["jobs", project.id],
    queryFn: () => api.jobs(project.id),
    refetchInterval: 3500,
  });
  const jobQuery = useQuery({
    queryKey: ["job", selectedId],
    queryFn: () => api.job(selectedId!),
    enabled: Boolean(selectedId),
    refetchInterval: 2500,
  });

  useEffect(() => {
    if (!selectedId && jobs.data?.length) setSelectedId(jobs.data[0].id);
  }, [jobs.data, selectedId]);

  useEffect(() => {
    if (jobQuery.data) setLiveJob(jobQuery.data);
  }, [jobQuery.data]);

  const onLiveJob = useCallback(
    (job: Job) => {
      setLiveJob(job);
      if (TERMINAL.includes(job.status)) {
        const marker = `${job.id}:${job.status}`;
        if (terminalRef.current !== marker) {
          terminalRef.current = marker;
          queryClient.invalidateQueries({ queryKey: ["jobs", project.id] });
          queryClient.invalidateQueries({ queryKey: ["project", project.id] });
          queryClient.invalidateQueries({ queryKey: ["dashboard"] });
          queryClient.invalidateQueries({ queryKey: ["persona", project.id] });
          queryClient.invalidateQueries({ queryKey: ["skills", project.id] });
        }
      }
    },
    [project.id, queryClient],
  );
  useJobStream(selectedId, onLiveJob);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["jobs", project.id] });
    queryClient.invalidateQueries({ queryKey: ["project", project.id] });
    queryClient.invalidateQueries({ queryKey: ["persona", project.id] });
    queryClient.invalidateQueries({ queryKey: ["skills", project.id] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const start = useMutation({
    mutationFn: (kind: "distill" | "compile") =>
      api.createJob(project.id, {
        kind,
        provider_id: providerId || null,
        run_llm_evals: kind === "compile" ? runLlmEvals : false,
      }),
    onSuccess: (job) => {
      setSelectedId(job.id);
      setLiveJob(job);
      refresh();
      toast({ title: job.kind === "distill" ? "蒸馏已开始" : "编译已开始", variant: "success" });
    },
    onError: (error: Error) => toast({ title: "启动失败", description: error.message, variant: "error" }),
  });

  const control = useMutation({
    mutationFn: ({ action }: { action: "pause" | "resume" | "cancel" | "retry" }) => {
      if (!selectedId) throw new Error("没有选中的任务");
      if (action === "pause") return api.pauseJob(selectedId);
      if (action === "resume") return api.resumeJob(selectedId);
      if (action === "cancel") return api.cancelJob(selectedId);
      return api.retryJob(selectedId);
    },
    onSuccess: (job) => {
      setLiveJob(job);
      refresh();
    },
    onError: (error: Error) => toast({ title: "操作失败", description: error.message, variant: "error" }),
  });

  const job = liveJob?.id === selectedId ? liveJob : jobQuery.data;
  const stageKeys = job?.kind === "compile" ? COMPILE_STAGES : DISTILL_STAGES;
  const stageMap = useMemo(() => new Map((job?.stages || []).map((stage) => [stage.stage, stage])), [job?.stages]);
  const running = job && ["queued", "running"].includes(job.status);

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>运行控制台</CardTitle>
            <CardDescription>
              蒸馏任务把资料变成待审核断言；审核后运行编译任务，生成 Skills、评测与人物包。没有配置模型时使用离线启发式抽取。
            </CardDescription>
          </div>
          <Badge tone={providerId ? "primary" : "neutral"}>{providerId ? "LLM 抽取" : "离线启发式"}</Badge>
        </CardHeader>
        <CardContent className="grid grid-cols-1 items-end gap-3 pt-0 lg:grid-cols-[1fr_auto_auto]">
          <label>
            <span className="label">本阶段模型</span>
            <Select value={providerId} onChange={(event) => setProviderId(event.target.value)}>
              <option value="">离线启发式（不调用模型）</option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name} · {provider.model_id}
                </option>
              ))}
            </Select>
          </label>
          <label className="flex h-10 items-center gap-2 rounded-xl border px-3 text-xs text-muted">
            <input
              type="checkbox"
              checked={runLlmEvals}
              onChange={(event) => setRunLlmEvals(event.target.checked)}
              className="h-4 w-4 accent-[hsl(var(--primary))]"
            />
            编译时运行 LLM 评测
          </label>
          <div className="flex gap-2">
            <Button variant="secondary" loading={start.isPending} onClick={() => start.mutate("distill")}>
              <Play className="h-4 w-4" />
              开始蒸馏
            </Button>
            <Button
              variant="primary"
              loading={start.isPending}
              onClick={() => start.mutate("compile")}
              disabled={project.approved_count === 0}
              title={project.approved_count === 0 ? "请先在审核收件箱批准至少一条断言" : "编译已批准断言"}
            >
              <FlaskConical className="h-4 w-4" />
              编译 Skills
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[320px_1fr]">
        <Card className="overflow-hidden">
          <CardHeader>
            <div>
              <CardTitle>任务历史</CardTitle>
              <CardDescription>最近 100 条</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="max-h-[720px] space-y-2 overflow-auto pt-0">
            {jobs.isLoading ? (
              <div className="py-10 text-center text-xs text-muted">加载中…</div>
            ) : !jobs.data?.length ? (
              <EmptyState icon={<FlaskConical className="h-5 w-5" />} title="还没有任务" description="点击上方按钮开始第一次蒸馏。" />
            ) : (
              jobs.data.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setSelectedId(item.id);
                    setLiveJob(null);
                  }}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    selectedId === item.id ? "border-primary/40 bg-primary/5" : "hover:bg-elevated"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold">{item.kind === "distill" ? "蒸馏" : "编译"}</span>
                    <StatusBadge status={item.status} />
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[10px] text-muted">
                    <span>{stageLabels[item.current_stage] || item.current_stage || "等待开始"}</span>
                    <span>{relativeTime(item.created_at)}</span>
                  </div>
                  <Progress className="mt-2" value={item.progress} tone={item.status === "failed" ? "danger" : item.status === "completed" ? "success" : "primary"} />
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>{job ? (job.kind === "distill" ? "蒸馏流水线" : "Skills 编译流水线") : "任务详情"}</CardTitle>
              <CardDescription>
                {job
                  ? `${job.id} · 创建于 ${formatDate(job.created_at)}`
                  : "从左侧选择一个任务，或启动新任务。"}
              </CardDescription>
            </div>
            {job ? (
              <div className="flex items-center gap-2">
                <StatusBadge status={job.status} />
                {job.status === "running" ? (
                  <Button size="sm" variant="secondary" onClick={() => control.mutate({ action: "pause" })}>
                    <Pause className="h-3.5 w-3.5" /> 暂停
                  </Button>
                ) : null}
                {job.status === "paused" ? (
                  <Button size="sm" variant="primary" onClick={() => control.mutate({ action: "resume" })}>
                    <Play className="h-3.5 w-3.5" /> 恢复
                  </Button>
                ) : null}
                {["queued", "running", "paused"].includes(job.status) ? (
                  <Button size="sm" variant="ghost" onClick={() => control.mutate({ action: "cancel" })}>
                    <Square className="h-3.5 w-3.5" /> 取消
                  </Button>
                ) : null}
                {["failed", "cancelled"].includes(job.status) ? (
                  <Button size="sm" variant="secondary" onClick={() => control.mutate({ action: "retry" })}>
                    <RotateCcw className="h-3.5 w-3.5" /> 重试
                  </Button>
                ) : null}
              </div>
            ) : null}
          </CardHeader>
          <CardContent className="pt-0">
            {!job ? (
              <EmptyState
                icon={<FlaskConical className="h-5 w-5" />}
                title="选择或启动一个任务"
                description="蒸馏会先解析资料、提取断言并等待审核；编译会消费已批准断言并生成 Skills。"
              />
            ) : (
              <div className="space-y-4">
                <div className="rounded-xl border bg-elevated/40 p-4">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium">{stageLabels[job.current_stage] || job.current_stage || "等待开始"}</span>
                    <span className="text-muted">{job.progress}%</span>
                  </div>
                  <Progress
                    className="mt-2"
                    value={job.progress}
                    tone={job.status === "failed" ? "danger" : job.status === "completed" ? "success" : "primary"}
                  />
                  <div className="mt-2 flex items-center gap-2 text-[10px] text-muted">
                    <Clock className="h-3 w-3" />
                    {job.started_at ? `开始于 ${relativeTime(job.started_at)}` : "尚未开始"}
                    {job.finished_at ? ` · 结束于 ${relativeTime(job.finished_at)}` : ""}
                  </div>
                </div>

                {job.error ? <Alert tone="danger" title="任务失败">{job.error}</Alert> : null}
                {job.status === "waiting_for_review" ? (
                  <Alert tone="warning" title="等待人工审核">
                    蒸馏已完成。请在审核收件箱批准或驳回断言，然后回到这里运行编译任务。
                    <div className="mt-2">
                      <Button size="sm" variant="primary" onClick={() => setTab("review")}>
                        去审核断言 <ArrowRight className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </Alert>
                ) : null}

                <div className="grid gap-2">
                  {stageKeys.map((key, index) => {
                    const stage = stageMap.get(key);
                    return (
                      <StageRow
                        key={key}
                        index={index}
                        stageKey={key}
                        stage={stage}
                        jobStatus={job.status}
                        isLast={index === stageKeys.length - 1}
                      />
                    );
                  })}
                </div>

                {job.result?.extract ? (
                  <ResultSummary job={job} />
                ) : null}
                {job.result?.export_id ? (
                  <Alert tone="success" title="人物包已生成">
                    导出 ID：{job.result.export_id}
                    <div className="mt-2">
                      <Button size="sm" variant="secondary" onClick={() => setTab("exports")}>
                        打开导出 <ArrowRight className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </Alert>
                ) : null}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StageRow({
  index,
  stageKey,
  stage,
  jobStatus,
  isLast,
}: {
  index: number;
  stageKey: string;
  stage?: Stage;
  jobStatus: string;
  isLast: boolean;
}) {
  const status = stage?.status || "pending";
  const icon =
    status === "succeeded" ? (
      <CheckCircle2 className="h-4 w-4 text-success" />
    ) : status === "failed" ? (
      <XCircle className="h-4 w-4 text-danger" />
    ) : status === "running" ? (
      <Loader2 className="h-4 w-4 animate-spin text-info" />
    ) : (
      <Circle className="h-4 w-4 text-muted/40" />
    );
  const output = stage?.output || {};
  const summary = summarizeOutput(stageKey, output);
  return (
    <div className="relative flex gap-3 rounded-xl border px-3 py-2.5">
      <div className="flex flex-col items-center">
        <span className="mt-0.5">{icon}</span>
        {!isLast ? <span className="mt-1 h-full w-px bg-border" /> : null}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-medium">
            {index + 1}. {stageLabels[stageKey] || stageKey}
          </span>
          <div className="flex items-center gap-2">
            {stage?.attempt && stage.attempt > 1 ? <Badge tone="warning">第 {stage.attempt} 次</Badge> : null}
            <StatusBadge status={status} />
          </div>
        </div>
        {summary ? <p className="mt-1 text-[11px] leading-5 text-muted">{summary}</p> : null}
        {stage?.error ? <p className="mt-1 text-[11px] leading-5 text-danger">{truncate(stage.error, 220)}</p> : null}
      </div>
    </div>
  );
}

function summarizeOutput(stage: string, output: Record<string, any>): string {
  if (!output || !Object.keys(output).length) return "";
  try {
    if (stage === "s02_ingest" || stage === "s03_parse") {
      return `解析 ${output.parsed ?? "—"} 份，失败 ${output.failed ?? "—"} 份`;
    }
    if (stage === "s05_chunk") return `${output.chunks ?? "—"} 个文本块`;
    if (stage === "s06_corpus_map") {
      const terms = (output.top_terms || []).slice(0, 5).map((item: any) => item.term).join("、");
      return terms ? `高频主题：${terms}` : "资料地图已生成";
    }
    if (stage === "s07_extract") {
      return `${output.claims ?? 0} 条断言 · ${output.mode || ""}${output.warnings?.length ? ` · ${output.warnings.length} 条警告` : ""}`;
    }
    if (stage === "s08_ground") return `已定位 ${output.grounded ?? 0} 条，未定位 ${output.ungrounded ?? 0} 条`;
    if (stage === "s09_conflicts") return `${output.open ?? 0} 个候选冲突`;
    if (stage === "s10_consolidate") return `${output.unique_claims ?? 0} 条唯一断言，待审核 ${output.pending ?? 0} 条`;
    if (stage === "s11_compose") return `${output.skills?.length ?? 0} 个能力分组`;
    if (stage === "s12_compile") return `生成 ${output.skills?.length ?? 0} 个 Skills`;
    if (stage === "s13_validate") return `通过 ${output.validated ?? 0} 个静态校验`;
    if (stage === "s15_package") return `导出包：${output.export_id || "已生成"}`;
    return truncate(JSON.stringify(output), 120);
  } catch {
    return "";
  }
}

function ResultSummary({ job }: { job: Job }) {
  const extract = job.result?.extract || {};
  const consolidate = job.result?.consolidate || {};
  const validation = job.result?.validation || {};
  return (
    <div className="rounded-xl border bg-elevated/40 p-4">
      <p className="text-xs font-semibold">本次结果</p>
      <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
        <div>
          <p className="text-muted">抽取断言</p>
          <p className="mt-1 font-semibold">{extract.claims ?? consolidate.claims ?? "—"}</p>
        </div>
        <div>
          <p className="text-muted">待审核</p>
          <p className="mt-1 font-semibold">{consolidate.pending ?? "—"}</p>
        </div>
        <div>
          <p className="text-muted">模式</p>
          <p className="mt-1 font-semibold">{extract.mode || "—"}</p>
        </div>
      </div>
      {extract.warnings?.length ? (
        <div className="mt-3 space-y-1">
          {extract.warnings.slice(0, 3).map((warning: string) => (
            <p key={warning} className="text-[10px] leading-5 text-warning">· {warning}</p>
          ))}
        </div>
      ) : null}
      {validation && Object.keys(validation).length ? (
        <p className="mt-3 text-[10px] text-muted">
          Skills 校验：{Object.values(validation).filter((item: any) => item?.ok).length}/{Object.keys(validation).length} 通过
        </p>
      ) : null}
    </div>
  );
}
