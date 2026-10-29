import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  Boxes,
  ClipboardCheck,
  Database,
  FlaskConical,
  GitBranch,
  ListChecks,
  Play,
  Sparkles,
  Users,
} from "lucide-react";
import { api } from "../api";
import type { Project, Provider } from "../types";
import {
  Badge,
  Button,
  PageHeader,
  Progress,
  Spinner,
  StatusBadge,
  Tabs,
  useToast,
} from "../ui";
import { OverviewTab } from "./project/Overview";
import { SourcesTab } from "./project/Sources";
import { PersonaTab } from "./project/Persona";
import { PipelineTab } from "./project/Pipeline";
import { ReviewTab } from "./project/Review";
import { SkillsTab } from "./project/Skills";
import { EvalsTab } from "./project/Evals";
import { ExportsTab } from "./project/Exports";

export type ProjectTabProps = {
  project: Project;
  providers: Provider[];
  setTab: (tab: string) => void;
};

const tabs = [
  { value: "overview", label: "概览" },
  { value: "sources", label: "资料库" },
  { value: "persona", label: "人物画像" },
  { value: "review", label: "审核收件箱" },
  { value: "pipeline", label: "蒸馏流水线" },
  { value: "skills", label: "Skills" },
  { value: "evals", label: "评估" },
  { value: "exports", label: "导出" },
];

export function ProjectWorkspacePage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  const queryClient = useQueryClient();
  const toast = useToast();

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.project(projectId),
    enabled: Boolean(projectId),
  });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const jobs = useQuery({
    queryKey: ["jobs", projectId],
    queryFn: () => api.jobs(projectId),
    enabled: Boolean(projectId),
    refetchInterval: 3500,
  });

  const setTab = (value: string) => {
    params.set("tab", value);
    setParams(params, { replace: true });
  };

  const createJob = useMutation({
    mutationFn: (kind: "distill" | "compile") =>
      api.createJob(projectId, {
        kind,
        provider_id: project.data?.provider_id || null,
        run_llm_evals: false,
      }),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["jobs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      toast({
        title: job.kind === "distill" ? "蒸馏任务已开始" : "Skills 编译任务已开始",
        description: "可在流水线中查看实时进度。",
        variant: "success",
      });
      setTab("pipeline");
    },
    onError: (error: Error) => toast({ title: "无法启动任务", description: error.message, variant: "error" }),
  });

  const latestJob = jobs.data?.[0];
  const activeJob = latestJob && ["queued", "running", "paused"].includes(latestJob.status);

  const nextAction = useMemo(() => {
    if (!project.data) return null;
    if (activeJob)
      return { label: "查看任务", icon: <Play className="h-4 w-4" />, onClick: () => setTab("pipeline") };
    if (project.data.source_count === 0)
      return { label: "导入资料", icon: <Database className="h-4 w-4" />, onClick: () => setTab("sources") };
    if (project.data.claim_count === 0)
      return {
        label: "开始蒸馏",
        icon: <Play className="h-4 w-4" />,
        onClick: () => createJob.mutate("distill"),
      };
    if (project.data.approved_count === 0)
      return { label: "审核断言", icon: <ClipboardCheck className="h-4 w-4" />, onClick: () => setTab("review") };
    if (project.data.skill_count === 0)
      return {
        label: "编译 Skills",
        icon: <Boxes className="h-4 w-4" />,
        onClick: () => createJob.mutate("compile"),
      };
    return { label: "导出人物包", icon: <ArrowRight className="h-4 w-4" />, onClick: () => setTab("exports") };
  }, [project.data, createJob, activeJob]);

  if (project.isLoading) {
    return <div className="flex h-80 items-center justify-center"><Spinner className="h-6 w-6" /></div>;
  }
  if (project.isError || !project.data) {
    return (
      <div className="mx-auto max-w-3xl py-16 text-center">
        <h2 className="text-lg font-semibold">项目不存在或已归档</h2>
        <p className="mt-2 text-sm text-muted">{project.error instanceof Error ? project.error.message : ""}</p>
        <Link to="/projects" className="mt-4 inline-flex text-sm text-primary hover:underline">
          返回项目列表
        </Link>
      </div>
    );
  }

  const data = project.data;
  const providerList = providers.data || [];
  const tabProps: ProjectTabProps = { project: data, providers: providerList, setTab };

  return (
    <div className="mx-auto max-w-[1440px] animate-in">
      <Link to="/projects" className="mb-4 inline-flex items-center gap-1.5 text-xs text-muted hover:text-text">
        <ArrowLeft className="h-3.5 w-3.5" />
        返回项目列表
      </Link>

      <PageHeader
        eyebrow={data.codename || "人物项目"}
        title={data.name}
        description={data.purpose || "尚未填写项目用途。"}
        actions={
          <>
            {!activeJob && data.claim_count > 0 ? (
              <Button variant="secondary" onClick={() => createJob.mutate("distill")} loading={createJob.isPending}>
                <Play className="h-4 w-4" />
                重新蒸馏
              </Button>
            ) : null}
            {nextAction ? (
              <Button variant="primary" onClick={nextAction.onClick} loading={createJob.isPending}>
                {nextAction.icon}
                {nextAction.label}
              </Button>
            ) : null}
          </>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-5">
        <ProjectMetric icon={<Database className="h-4 w-4" />} label="资料" value={data.source_count} />
        <ProjectMetric icon={<GitBranch className="h-4 w-4" />} label="断言" value={data.claim_count} />
        <ProjectMetric
          icon={<ClipboardCheck className="h-4 w-4" />}
          label="已批准"
          value={`${data.approved_count}/${data.claim_count}`}
        />
        <ProjectMetric icon={<Boxes className="h-4 w-4" />} label="Skills" value={data.skill_count} />
        <ProjectMetric
          icon={<FlaskConical className="h-4 w-4" />}
          label="最新任务"
          value={latestJob ? <StatusBadge status={latestJob.status} /> : <span className="text-xs text-muted">未运行</span>}
        />
      </div>

      <Tabs
        items={tabs.map((item) => ({
          ...item,
          count:
            item.value === "sources"
              ? data.source_count
              : item.value === "review"
                ? data.pending_count
                : item.value === "skills"
                  ? data.skill_count
                  : undefined,
        }))}
        value={tab}
        onChange={setTab}
        className="mb-5"
      />

      <div key={tab} className="animate-in">
        {tab === "overview" ? <OverviewTab {...tabProps} /> : null}
        {tab === "sources" ? <SourcesTab {...tabProps} /> : null}
        {tab === "persona" ? <PersonaTab {...tabProps} /> : null}
        {tab === "pipeline" ? <PipelineTab {...tabProps} /> : null}
        {tab === "review" ? <ReviewTab {...tabProps} /> : null}
        {tab === "skills" ? <SkillsTab {...tabProps} /> : null}
        {tab === "evals" ? <EvalsTab {...tabProps} /> : null}
        {tab === "exports" ? <ExportsTab {...tabProps} /> : null}
      </div>
    </div>
  );
}

function ProjectMetric({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border bg-surface px-3.5 py-2.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-base font-semibold">{value}</div>
    </div>
  );
}
