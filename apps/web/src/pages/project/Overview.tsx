import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Circle,
  Clock,
  Database,
  FileText,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api } from "../../api";
import type { ProjectTabProps } from "../ProjectWorkspace";
import { SearchPanel } from "../../components/SearchPanel";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DimensionBadge,
  EmptyState,
  Progress,
  Spinner,
  StatusBadge,
} from "../../ui";
import { formatDate, relativeTime, truncate } from "../../lib/format";
import { stageLabels } from "../../lib/labels";

export function OverviewTab({ project, setTab }: ProjectTabProps) {
  const persona = useQuery({ queryKey: ["persona", project.id], queryFn: () => api.persona(project.id) });
  const sources = useQuery({ queryKey: ["sources", project.id], queryFn: () => api.sources(project.id) });
  const jobs = useQuery({ queryKey: ["jobs", project.id], queryFn: () => api.jobs(project.id) });
  const skills = useQuery({ queryKey: ["skills", project.id], queryFn: () => api.skills(project.id) });
  const latestJob = jobs.data?.[0];

  const steps = [
    {
      title: "导入资料",
      done: project.source_count > 0,
      text: `${project.source_count} 份资料`,
      action: () => setTab("sources"),
    },
    {
      title: "蒸馏断言",
      done: project.claim_count > 0,
      text: `${project.claim_count} 条断言`,
      action: () => setTab("pipeline"),
    },
    {
      title: "人工审核",
      done: project.approved_count > 0,
      text: `${project.approved_count} 条已批准`,
      action: () => setTab("review"),
    },
    {
      title: "编译 Skills",
      done: project.skill_count > 0,
      text: `${project.skill_count} 个 Skills`,
      action: () => setTab("skills"),
    },
  ];
  const completed = steps.filter((step) => step.done).length;

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
      <div className="space-y-5 xl:col-span-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>项目定义</CardTitle>
              <CardDescription>用途、授权与边界是蒸馏和导出的前置条件</CardDescription>
            </div>
            <Badge tone={project.status === "active" ? "success" : "neutral"}>
              {project.status === "active" ? "进行中" : "已归档"}
            </Badge>
          </CardHeader>
          <CardContent className="grid gap-4 pt-0">
            <InfoRow label="项目代号" value={project.codename || "未设置"} />
            <InfoRow label="用途" value={project.purpose || "未填写"} />
            <InfoRow label="授权/来源" value={project.authorization_note || "未填写"} />
            <InfoRow label="禁止用途" value={project.prohibited_uses || "未填写"} />
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-[11px] text-muted">目标平台</span>
              {(project.target_platforms || []).map((platform) => (
                <Badge key={platform} tone="neutral">{platform}</Badge>
              ))}
              {!project.target_platforms?.length ? <span className="text-xs text-muted">未指定</span> : null}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>人物画像覆盖</CardTitle>
              <CardDescription>已批准断言按维度分布；审核后才可进入编译</CardDescription>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setTab("persona")}>
              查看画像 <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </CardHeader>
          <CardContent className="pt-0">
            {persona.isLoading ? (
              <div className="flex h-32 items-center justify-center"><Spinner /></div>
            ) : persona.data ? (
              <div className="grid gap-3 md:grid-cols-2">
                {persona.data.dimensions.map((dimension) => {
                  const ratio = dimension.total ? Math.round((dimension.approved / dimension.total) * 100) : 0;
                  return (
                    <div key={dimension.dimension} className="rounded-xl border p-3.5">
                      <div className="flex items-center justify-between gap-2">
                        <DimensionBadge dimension={dimension.dimension} />
                        <span className="text-xs text-muted">{dimension.approved}/{dimension.total}</span>
                      </div>
                      <Progress className="mt-3" value={ratio} tone={dimension.approved ? "success" : "primary"} />
                      <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-muted">
                        {dimension.statement_samples[0] || "暂无已批准样本"}
                      </p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <Alert tone="warning" title="暂无画像数据">先运行蒸馏流水线，然后在审核收件箱中批准断言。</Alert>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>最近资料</CardTitle>
              <CardDescription>解析状态与来源定位</CardDescription>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setTab("sources")}>
              打开资料库 <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </CardHeader>
          <CardContent className="pt-0">
            {sources.data?.length ? (
              <div className="space-y-2">
                {sources.data.slice(0, 4).map((source) => (
                  <div key={source.id} className="flex items-center gap-3 rounded-xl border px-3 py-2.5">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-elevated text-muted">
                      <FileText className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium">{source.original_name}</p>
                      <p className="mt-0.5 text-[10px] text-muted">
                        {source.chunk_count} 块 · {relativeTime(source.created_at)}
                      </p>
                    </div>
                    <StatusBadge status={source.status} />
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<Database className="h-5 w-5" />}
                title="还没有资料"
                description="支持 PDF、DOCX、Markdown、聊天记录、代码、扫描件与音视频（可选依赖）。"
                action={<Button variant="primary" onClick={() => setTab("sources")}>导入资料</Button>}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="space-y-5">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>推进路线</CardTitle>
              <CardDescription>{completed}/4 步已完成</CardDescription>
            </div>
            <Progress className="w-20" value={(completed / 4) * 100} tone={completed === 4 ? "success" : "primary"} />
          </CardHeader>
          <CardContent className="space-y-1 pt-0">
            {steps.map((step, index) => (
              <button
                key={step.title}
                type="button"
                onClick={step.action}
                className="flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left transition hover:bg-elevated"
              >
                <span className={step.done ? "text-success" : "text-muted/50"}>
                  {step.done ? <CheckCircle2 className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-medium">{index + 1}. {step.title}</span>
                  <span className="block text-[10px] text-muted">{step.text}</span>
                </span>
                <ArrowRight className="h-3.5 w-3.5 text-muted/50" />
              </button>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>最新任务</CardTitle>
              <CardDescription>最近一次流水线运行</CardDescription>
            </div>
            {latestJob ? <StatusBadge status={latestJob.status} /> : null}
          </CardHeader>
          <CardContent className="pt-0">
            {latestJob ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium">{latestJob.kind === "distill" ? "蒸馏" : "编译"}</span>
                  <span className="text-muted">{latestJob.progress}%</span>
                </div>
                <Progress value={latestJob.progress} tone={latestJob.status === "failed" ? "danger" : latestJob.status === "completed" ? "success" : "primary"} />
                <div className="flex items-center gap-2 text-[11px] text-muted">
                  <Clock className="h-3 w-3" />
                  {latestJob.current_stage ? stageLabels[latestJob.current_stage] || latestJob.current_stage : "等待开始"}
                  <span>·</span>
                  {formatDate(latestJob.created_at)}
                </div>
                {latestJob.error ? <Alert tone="danger">{latestJob.error}</Alert> : null}
                <Button size="sm" variant="secondary" className="w-full" onClick={() => setTab("pipeline")}>
                  打开流水线
                </Button>
              </div>
            ) : (
              <EmptyState
                icon={<Sparkles className="h-5 w-5" />}
                title="还没有运行记录"
                description={project.source_count ? "资料已就绪，开始第一次蒸馏。" : "先导入资料，再运行蒸馏。"}
                action={
                  <Button variant="primary" onClick={() => setTab(project.source_count ? "pipeline" : "sources")}>
                    {project.source_count ? "开始蒸馏" : "导入资料"}
                  </Button>
                }
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>人物包资产</CardTitle>
              <CardDescription>四类资产分开分发</CardDescription>
            </div>
            <BookOpenCheck className="h-4 w-4 text-muted" />
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            <AssetRow label="Persona Profile" value={project.approved_count ? "已就绪" : "待审核"} done={project.approved_count > 0} />
            <AssetRow label="Agent Skills" value={`${skills.data?.length || 0} 个`} done={Boolean(skills.data?.length)} />
            <AssetRow label="Knowledge / RAG" value="随包导出" done={Boolean(skills.data?.length)} />
            <AssetRow label="Audit / Evals" value="持续记录" done={Boolean(skills.data?.length)} />
            <div className="pt-1">
              <Button size="sm" variant="secondary" className="w-full" onClick={() => setTab("exports")}>
                <ShieldCheck className="h-3.5 w-3.5" />
                查看导出
              </Button>
            </div>
          </CardContent>
        </Card>

        <SearchPanel projectId={project.id} />
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-3 border-b border-border/60 pb-3 last:border-0 last:pb-0">
      <span className="text-[11px] text-muted">{label}</span>
      <span className="text-xs leading-5">{value}</span>
    </div>
  );
}

function AssetRow({ label, value, done }: { label: string; value: string; done: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-elevated/50 px-2.5 py-2">
      <span className="text-[11px] text-muted">{label}</span>
      <span className={done ? "text-[11px] font-medium text-success" : "text-[11px] text-muted"}>{value}</span>
    </div>
  );
}
