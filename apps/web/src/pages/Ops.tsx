import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Database,
  Eye,
  HardDrive,
  Layers,
  ServerCog,
  XCircle,
} from "lucide-react";
import { api } from "../api";
import {
  Alert,
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  PageHeader,
  Progress,
  Spinner,
} from "../ui";

function formatTokens(value: number | undefined | null): string {
  if (value === undefined || value === null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

export function OpsPage() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 10000 });
  const ready = useQuery({ queryKey: ["ready"], queryFn: api.ready, refetchInterval: 15000 });
  const usage = useQuery({ queryKey: ["usage"], queryFn: api.usage });

  if (stats.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const runtime = stats.data?.runtime;
  const checks = ready.data?.checks || {};
  const totals = usage.data?.totals;
  const hasUsage = Boolean(totals && totals.calls > 0);

  return (
    <div className="mx-auto max-w-[1200px] animate-in">
      <PageHeader
        eyebrow="可观测性"
        title="运行状态与用量"
        description="健康检查区分存活与就绪：存活探针不触碰数据库，就绪探针校验数据库、可写目录与向量后端，可直接接入容器编排。"
        actions={
          <Badge tone={ready.data?.status === "ready" ? "success" : "warning"}>
            {ready.data?.status === "ready" ? "就绪" : ready.data?.status || "检查中"}
          </Badge>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="项目" value={stats.data?.projects ?? 0} icon={<Layers className="h-4 w-4" />} />
        <Metric label="资料" value={stats.data?.sources ?? 0} icon={<Database className="h-4 w-4" />} />
        <Metric label="Skills" value={stats.data?.skills ?? 0} icon={<CheckCircle2 className="h-4 w-4" />} />
        <Metric
          label="活跃任务"
          value={stats.data?.jobs_active ?? 0}
          icon={<Activity className="h-4 w-4" />}
          hint={`共 ${stats.data?.jobs ?? 0} 个任务`}
        />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>就绪检查</CardTitle>
              <CardDescription>GET /api/v1/ready · 编排系统据此决定是否转发流量</CardDescription>
            </div>
            <ServerCog className="h-4 w-4 text-muted" />
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {ready.isError ? (
              <Alert tone="danger" title="就绪检查失败">
                服务可能仍在启动，或在依赖不可用时被正确标记为未就绪。
              </Alert>
            ) : !ready.data ? (
              <div className="flex h-24 items-center justify-center">
                <Spinner />
              </div>
            ) : (
              Object.entries(checks).map(([key, value]: [string, any]) => {
                const ok = value?.status === "ok";
                return (
                  <div
                    key={key}
                    className="flex items-start justify-between gap-3 rounded-xl border px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="text-xs font-medium">{key}</p>
                      <p className="mt-0.5 break-all font-mono text-[10px] text-muted">
                        {typeof value === "object"
                          ? Object.entries(value)
                              .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
                              .join(" · ")
                          : String(value)}
                      </p>
                    </div>
                    {ok ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                    ) : (
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
                    )}
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>运行时</CardTitle>
              <CardDescription>由环境变量决定，重启生效</CardDescription>
            </div>
            <Cpu className="h-4 w-4 text-muted" />
          </CardHeader>
          <CardContent className="space-y-3 pt-0">
            <Row label="版本" value={runtime?.version || "—"} mono />
            <Row label="运行环境" value={runtime?.env || "—"} />
            <Row label="数据库" value={runtime?.database || "—"} />
            <Row
              label="任务执行"
              value={runtime?.inline_worker ? "进程内 Worker" : "独立 Worker 进程"}
            />
            <Row label="Worker ID" value={runtime?.worker_id || "—"} mono />
            <Row label="租约时长" value={`${runtime?.lease_seconds ?? "—"} 秒`} />
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <div>
            <CardTitle>模型用量</CardTitle>
            <CardDescription>{usage.data?.note || "仅统计供应商实际返回的用量。"}</CardDescription>
          </div>
          <Badge tone={hasUsage ? "info" : "neutral"}>
            {hasUsage ? `${totals?.calls} 次调用` : "未统计"}
          </Badge>
        </CardHeader>
        <CardContent className="pt-0">
          {!hasUsage ? (
            <Alert tone="info" title="尚无用量数据">
              用量只在配置了模型并实际运行蒸馏或评测后产生。离线启发式模式不调用模型，因此不会出现 Token 统计。
            </Alert>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Metric label="输入 Token" value={formatTokens(totals?.input_tokens)} />
                <Metric label="输出 Token" value={formatTokens(totals?.output_tokens)} />
                <Metric label="合计 Token" value={formatTokens(totals?.total_tokens)} />
                <Metric label="调用次数" value={totals?.calls ?? 0} />
              </div>
              <div className="mt-4 space-y-2">
                {(usage.data?.projects || []).map((item) => {
                  const share =
                    totals && totals.total_tokens
                      ? (item.total_tokens / totals.total_tokens) * 100
                      : 0;
                  return (
                    <div key={item.project_id} className="rounded-xl border p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-medium">{item.project_name}</span>
                        <span className="font-mono text-[11px] text-muted">
                          {formatTokens(item.total_tokens)} · {item.calls} 次 · {item.jobs} 个任务
                        </span>
                      </div>
                      <Progress className="mt-2" value={share} />
                      {Object.keys(item.models || {}).length ? (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {Object.entries(item.models).map(([model, value]) => (
                            <Badge key={model} tone="neutral">
                              {model} · {formatTokens(value.total_tokens)}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <div>
            <CardTitle>部署形态</CardTitle>
            <CardDescription>同一镜像支持三种部署方式，差异只在环境变量</CardDescription>
          </div>
          <HardDrive className="h-4 w-4 text-muted" />
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 pt-0 lg:grid-cols-3">
          <DeploymentCard
            title="单机本地"
            tag="默认"
            lines={[
              "SQLite + sqlite-vec",
              "API 进程内嵌 Worker",
              "只监听 127.0.0.1",
            ]}
            command="./deploy/scripts/start.sh"
          />
          <DeploymentCard
            title="Docker Compose"
            tag="团队"
            lines={[
              "同一镜像，api / worker 分离",
              "migrate 一次性服务先行",
              "命名卷持久化 data 与 exports",
            ]}
            command="docker compose -f deploy/compose.yaml up -d"
          />
          <DeploymentCard
            title="PostgreSQL"
            tag="可上云"
            lines={[
              "worker 可水平扩容",
              "lease_epoch 围栏防重复执行",
              "向量回退到精确余弦检索",
            ]}
            command="docker compose -f deploy/compose.postgres.yaml up -d"
          />
        </CardContent>
      </Card>

      <div className="mt-4">
        <Alert tone="warning" title="局域网共享前请确认">
          当前版本没有内置登录与多用户隔离。把浏览器暴露给他人意味着他人可以上传资料、读取证据、导出人物包。
          团队使用应放在可信网络内，并在前面加一层反向代理与访问控制。
        </Alert>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  icon,
  hint,
}: {
  label: string;
  value: number | string;
  icon?: React.ReactNode;
  hint?: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-muted">{label}</p>
          <p className="mt-1.5 text-xl font-semibold">{value}</p>
          {hint ? <p className="mt-0.5 text-[10px] text-muted">{hint}</p> : null}
        </div>
        {icon ? <div className="rounded-lg bg-primary/10 p-1.5 text-primary">{icon}</div> : null}
      </div>
    </Card>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border/60 pb-2.5 last:border-0 last:pb-0">
      <span className="text-[11px] text-muted">{label}</span>
      <span className={`max-w-[65%] break-all text-right text-xs ${mono ? "font-mono text-[10px]" : ""}`}>
        {value}
      </span>
    </div>
  );
}

function DeploymentCard({
  title,
  tag,
  lines,
  command,
}: {
  title: string;
  tag: string;
  lines: string[];
  command: string;
}) {
  return (
    <div className="rounded-xl border bg-elevated/40 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold">{title}</p>
        <Badge tone="primary">{tag}</Badge>
      </div>
      <ul className="mt-2 space-y-1">
        {lines.map((line) => (
          <li key={line} className="flex items-start gap-1.5 text-[11px] leading-5 text-muted">
            <Eye className="mt-1 h-3 w-3 shrink-0" />
            {line}
          </li>
        ))}
      </ul>
      <code className="mt-3 block break-all rounded-lg border bg-surface px-2 py-1.5 font-mono text-[10px] text-muted">
        {command}
      </code>
    </div>
  );
}