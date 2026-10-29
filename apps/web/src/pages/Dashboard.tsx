import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  BookOpenCheck,
  Boxes,
  ClipboardCheck,
  Database,
  FlaskConical,
  FolderKanban,
  GitBranch,
  Layers3,
  Plus,
  Sparkles,
  Upload,
  Wand2,
} from "lucide-react";
import { api } from "../api";
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
  PageHeader,
  Progress,
  Spinner,
  StatCard,
  StatusBadge,
  useToast,
} from "../ui";
import { relativeTime, truncate } from "../lib/format";
import { stageLabels } from "../lib/labels";

const flow = [
  { icon: Upload, title: "资料接入", text: "文档、聊天、代码、扫描件与音视频" },
  { icon: GitBranch, title: "证据蒸馏", text: "解析、分块、断言、冲突检测" },
  { icon: ClipboardCheck, title: "人工审核", text: "逐条核对证据，批准或驳回" },
  { icon: Boxes, title: "编译发布", text: "SKILL.md、人物包、评测与导出" },
];

export function DashboardPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  const demo = useMutation({
    mutationFn: api.createDemo,
    onSuccess: (result) => {
      toast({ title: "示例项目已创建", description: result.message, variant: "success" });
      navigate(`/projects/${result.project_id}`);
    },
    onError: (error: Error) => toast({ title: "创建失败", description: error.message, variant: "error" }),
  });

  if (dashboard.isLoading) {
    return (
      <div className="flex h-80 items-center justify-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (dashboard.isError || !dashboard.data) {
    return (
      <Alert tone="danger" title="无法连接后端">
        {dashboard.error instanceof Error ? dashboard.error.message : "请确认 API 已启动。"}
      </Alert>
    );
  }

  const data = dashboard.data;

  return (
    <div className="mx-auto max-w-[1400px] animate-in">
      <PageHeader
        eyebrow="Persona → Agent Skills"
        title="把一个人的能力，蒸馏成可执行的 Skills"
        description="从异构资料中提取专业能力、思维决策、表达风格与边界；每一条结论都有证据，经过人工审核后才进入可移植的 Agent Skills 包。"
        actions={
          <>
            <Button variant="secondary" onClick={() => navigate("/projects?new=1")}>
              <Plus className="h-4 w-4" />
              新建项目
            </Button>
            <Button variant="primary" loading={demo.isPending} onClick={() => demo.mutate()}>
              <Sparkles className="h-4 w-4" />
              创建示例项目
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-5">
        <StatCard label="人物项目" value={data.projects} icon={<FolderKanban className="h-4 w-4" />} />
        <StatCard label="资料" value={data.sources} icon={<Database className="h-4 w-4" />} tone="info" />
        <StatCard
          label="待审核断言"
          value={data.claims_pending}
          icon={<ClipboardCheck className="h-4 w-4" />}
          tone="warning"
          hint="审核后才可编译"
        />
        <StatCard label="Skills" value={data.skills} icon={<Boxes className="h-4 w-4" />} tone="success" />
        <StatCard
          label="运行任务"
          value={data.jobs_running}
          hint={data.jobs_failed ? `${data.jobs_failed} 个失败任务` : "队列正常"}
          icon={<FlaskConical className="h-4 w-4" />}
          tone={data.jobs_failed ? "danger" : "primary"}
        />
      </div>

      <Card className="mt-5 overflow-hidden">
        <CardContent className="p-0">
          <div className="grid grid-cols-1 divide-y divide-border sm:grid-cols-2 sm:divide-y-0 sm:divide-x xl:grid-cols-4">
            {flow.map((step, index) => (
              <div key={step.title} className="relative flex items-start gap-3 p-5">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <step.icon className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm font-semibold">{step.title}</p>
                  <p className="mt-1 text-xs leading-5 text-muted">{step.text}</p>
                </div>
                {index < flow.length - 1 ? (
                  <span className="absolute -right-2 top-1/2 z-10 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-full border bg-surface text-muted">
                    <ArrowRight className="h-2.5 w-2.5" />
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>最近的人物项目</CardTitle>
              <CardDescription>资料、断言与 Skills 的当前状态</CardDescription>
            </div>
            <Link to="/projects" className="text-xs font-medium text-primary hover:underline">
              查看全部
            </Link>
          </CardHeader>
          <CardContent className="pt-0">
            {data.recent_projects.length === 0 ? (
              <EmptyState
                icon={<Layers3 className="h-5 w-5" />}
                title="还没有项目"
                description="创建一个示例项目，或从空白项目开始导入资料。"
                action={
                  <Button variant="primary" loading={demo.isPending} onClick={() => demo.mutate()}>
                    <Sparkles className="h-4 w-4" />
                    创建示例项目
                  </Button>
                }
              />
            ) : (
              <div className="space-y-2">
                {data.recent_projects.map((project) => (
                  <Link
                    key={project.id}
                    to={`/projects/${project.id}`}
                    className="group flex items-center gap-4 rounded-xl border border-transparent px-3 py-3 transition hover:border-border hover:bg-elevated"
                  >
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-accent/10 text-primary">
                      <BookOpenCheck className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-semibold">{project.name}</p>
                        <Badge tone={project.status === "active" ? "success" : "neutral"}>
                          {project.status === "active" ? "进行中" : "已归档"}
                        </Badge>
                      </div>
                      <p className="mt-0.5 truncate text-xs text-muted">{truncate(project.purpose, 90) || "暂无项目说明"}</p>
                    </div>
                    <div className="hidden shrink-0 items-center gap-4 text-center text-xs text-muted sm:flex">
                      <div>
                        <p className="font-semibold text-text">{project.source_count}</p>
                        <p>资料</p>
                      </div>
                      <div>
                        <p className="font-semibold text-text">{project.approved_count}/{project.claim_count}</p>
                        <p>已批准</p>
                      </div>
                      <div>
                        <p className="font-semibold text-text">{project.skill_count}</p>
                        <p>Skills</p>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-muted/50 transition group-hover:translate-x-0.5 group-hover:text-primary" />
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>最近任务</CardTitle>
              <CardDescription>队列与流水线状态</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {data.recent_jobs.length === 0 ? (
              <EmptyState icon={<FlaskConical className="h-5 w-5" />} title="还没有任务" description="项目创建后，运行一次蒸馏即可看到进度。" />
            ) : (
              <div className="space-y-3">
                {data.recent_jobs.map((job) => (
                  <Link
                    key={job.id}
                    to={`/projects/${job.project_id}?tab=pipeline`}
                    className="block rounded-xl border p-3 transition hover:bg-elevated"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold">
                        {job.kind === "distill" ? "蒸馏任务" : "编译任务"}
                      </span>
                      <StatusBadge status={job.status} />
                    </div>
                    <div className="mt-2 flex items-center justify-between text-[11px] text-muted">
                      <span>{stageLabels[job.current_stage] || job.current_stage || "等待开始"}</span>
                      <span>{relativeTime(job.created_at)}</span>
                    </div>
                    <Progress
                      className="mt-2"
                      value={job.progress}
                      tone={job.status === "failed" ? "danger" : job.status === "completed" ? "success" : "primary"}
                    />
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <QuickCard
          icon={<Wand2 className="h-4 w-4" />}
          title="配置模型与 API"
          description="OpenAI Responses、Anthropic Messages、Gemini generateContent，参数可逐阶段覆盖。"
          to="/providers"
        />
        <QuickCard
          icon={<ClipboardCheck className="h-4 w-4" />}
          title="审核断言与冲突"
          description="每条断言并排显示原文证据、来源位置与冲突候选；批准后才进入编译。"
          to={data.recent_projects[0] ? `/projects/${data.recent_projects[0].id}?tab=review` : "/projects"}
        />
        <QuickCard
          icon={<Boxes className="h-4 w-4" />}
          title="导出人物模型包"
          description="生成 SKILL.md、references、evals、人物档案、证据台账与兼容性说明。"
          to={data.recent_projects[0] ? `/projects/${data.recent_projects[0].id}?tab=exports` : "/projects"}
        />
      </div>
    </div>
  );
}

function QuickCard({
  icon,
  title,
  description,
  to,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  to: string;
}) {
  return (
    <Link to={to} className="card card-hover group p-4">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-elevated text-primary">{icon}</div>
      <p className="mt-3 text-sm font-semibold">{title}</p>
      <p className="mt-1 text-xs leading-5 text-muted">{description}</p>
      <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary">
        打开 <ArrowRight className="h-3 w-3 transition group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}
