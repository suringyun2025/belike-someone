import { useQuery } from "@tanstack/react-query";
import {
  Database,
  FolderCog,
  HardDrive,
  KeyRound,
  ServerCog,
  ShieldCheck,
  Terminal,
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
  CodeBlock,
  PageHeader,
  Spinner,
} from "../ui";

export function SettingsPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  if (settings.isLoading) {
    return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  }

  const data = settings.data;

  return (
    <div className="mx-auto max-w-[1200px] animate-in">
      <PageHeader
        eyebrow="设置与运行信息"
        title="本地优先，证据可控"
        description="平台默认只监听 127.0.0.1，原始资料与导出包保存在本机；API Key 加密存储，日志不记录密钥或完整私密提示词。"
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>运行状态</CardTitle>
              <CardDescription>API、数据库与 Worker</CardDescription>
            </div>
            <Badge tone={health.data?.status === "ok" ? "success" : "danger"}>
              {health.data?.status === "ok" ? "运行中" : "不可用"}
            </Badge>
          </CardHeader>
          <CardContent className="space-y-3 pt-0">
            <InfoRow icon={<Database className="h-3.5 w-3.5" />} label="数据库" value={data?.database_url || "—"} mono />
            <InfoRow icon={<FolderCog className="h-3.5 w-3.5" />} label="数据目录" value={data?.data_dir || "—"} mono />
            <InfoRow icon={<HardDrive className="h-3.5 w-3.5" />} label="导出目录" value={data?.export_dir || "—"} mono />
            <InfoRow icon={<ServerCog className="h-3.5 w-3.5" />} label="Inline Worker" value={data?.inline_worker ? "已启用" : "独立进程"} />
            <InfoRow icon={<KeyRound className="h-3.5 w-3.5" />} label="API Key" value="Fernet 加密保存在本地数据目录" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>流水线参数</CardTitle>
              <CardDescription>环境变量控制，修改后重启生效</CardDescription>
            </div>
            <Terminal className="h-4 w-4 text-muted" />
          </CardHeader>
          <CardContent className="space-y-3 pt-0">
            <InfoRow label="单文件上传上限" value={`${data?.max_upload_mb ?? "—"} MB`} />
            <InfoRow label="分块大小" value={`${data?.chunk_chars ?? "—"} 字符`} />
            <InfoRow label="分块重叠" value={`${data?.chunk_overlap ?? "—"} 字符`} />
            <InfoRow label="单任务最大分块" value={String(data?.max_chunks_per_job ?? "—")} />
            <InfoRow label="多模型并发" value="由 Worker 串行调度；单任务内按阶段执行" />
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <div>
            <CardTitle>Agent Skills 规范约束</CardTitle>
            <CardDescription>编译与导出时自动检查</CardDescription>
          </div>
          <ShieldCheck className="h-4 w-4 text-muted" />
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 pt-0 sm:grid-cols-2 lg:grid-cols-4">
          <SpecCard label="name" value="≤ 64 字符，小写字母/数字/连字符" />
          <SpecCard label="description" value="≤ 1024 字符，含触发条件" />
          <SpecCard label="compatibility" value="≤ 500 字符" />
          <SpecCard label="渐进式披露" value="SKILL.md < 500 行 / < 5k tokens" />
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <div>
            <CardTitle>协议能力矩阵</CardTitle>
            <CardDescription>不同供应商对参数的支持并不一致</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>协议</th>
                  <th>JSON Schema</th>
                  <th>流式</th>
                  <th>工具</th>
                  <th>top_k</th>
                  <th>缓存用量</th>
                </tr>
              </thead>
              <tbody>
                {(meta.data?.protocols || []).map((protocol) => (
                  <tr key={protocol.value}>
                    <td className="text-xs font-medium">{protocol.label}</td>
                    <td><Yes value={protocol.capabilities.json_schema} /></td>
                    <td><Yes value={protocol.capabilities.streaming} /></td>
                    <td><Yes value={protocol.capabilities.tools} /></td>
                    <td><Yes value={protocol.capabilities.top_k} /></td>
                    <td><Yes value={protocol.capabilities.cache_usage} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <div>
            <CardTitle>本地开发命令</CardTitle>
            <CardDescription>在仓库根目录执行</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          <CodeBlock
            code={`# 依赖
uv sync --project apps/api
pnpm install --dir apps/web

# 启动 API（含 Inline Worker）
uv run --project apps/api uvicorn app.main:app --app-dir apps/api --reload --port 8000

# 启动前端
pnpm --dir apps/web dev

# 结构校验（可选）
npm i -g skills-ref
skills-ref validate <skill-dir>`}
          />
          <Alert tone="info" title="Python 版本">
            后端要求 Python 3.12；本机若只有 3.14，请先执行 <span className="font-mono">uv python install 3.12</span>。
          </Alert>
        </CardContent>
      </Card>
    </div>
  );
}

function InfoRow({
  icon,
  label,
  value,
  mono = false,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border/60 pb-2.5 last:border-0 last:pb-0">
      <span className="flex items-center gap-1.5 text-[11px] text-muted">{icon}{label}</span>
      <span className={`max-w-[70%] break-all text-right text-xs ${mono ? "font-mono text-[10px]" : ""}`}>{value}</span>
    </div>
  );
}

function SpecCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border bg-elevated/40 p-3">
      <p className="font-mono text-[11px] text-primary">{label}</p>
      <p className="mt-1 text-[11px] leading-5 text-muted">{value}</p>
    </div>
  );
}

function Yes({ value }: { value: boolean }) {
  return value ? <Badge tone="success">支持</Badge> : <Badge tone="neutral">不支持</Badge>;
}
