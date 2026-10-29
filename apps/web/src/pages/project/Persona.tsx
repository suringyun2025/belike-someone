import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDot,
  ClipboardCheck,
  Quote,
  ShieldAlert,
  Users,
} from "lucide-react";
import { api } from "../../api";
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
  DimensionBadge,
  EmptyState,
  Progress,
  Spinner,
  StatusBadge,
  useToast,
} from "../../ui";
import { relativeTime } from "../../lib/format";

export function PersonaTab({ project, setTab }: ProjectTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const persona = useQuery({ queryKey: ["persona", project.id], queryFn: () => api.persona(project.id) });
  const conflicts = useQuery({ queryKey: ["conflicts", project.id], queryFn: () => api.conflicts(project.id) });

  const resolve = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.updateConflict(id, { status, resolution: status === "resolved" ? "人工确认后保留差异" : "" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conflicts", project.id] });
      queryClient.invalidateQueries({ queryKey: ["persona", project.id] });
      toast({ title: "冲突状态已更新", variant: "success" });
    },
    onError: (error: Error) => toast({ title: "更新失败", description: error.message, variant: "error" }),
  });

  if (persona.isLoading) {
    return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  }
  if (!persona.data) {
    return <Alert tone="danger" title="无法加载人物画像">请稍后重试。</Alert>;
  }

  const data = persona.data;
  const openConflicts = (conflicts.data || []).filter((item) => item.status === "open");

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <SummaryCard icon={<CheckCircle2 className="h-4 w-4" />} label="已批准断言" value={data.approved_claims} tone="success" />
        <SummaryCard icon={<ClipboardCheck className="h-4 w-4" />} label="待审核" value={data.pending_claims} tone="warning" />
        <SummaryCard icon={<ShieldAlert className="h-4 w-4" />} label="开放冲突" value={data.conflicts_open} tone="danger" />
        <SummaryCard icon={<Users className="h-4 w-4" />} label="覆盖维度" value={`${data.dimensions.filter((item) => item.approved > 0).length}/6`} tone="primary" />
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>能力地图</CardTitle>
            <CardDescription>{data.summary}</CardDescription>
          </div>
          <Button size="sm" variant="secondary" onClick={() => setTab("review")}>
            <ClipboardCheck className="h-3.5 w-3.5" />
            去审核
          </Button>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="grid gap-3 lg:grid-cols-2">
            {data.dimensions.map((dimension) => (
              <div key={dimension.dimension} className="rounded-xl border p-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <DimensionBadge dimension={dimension.dimension} />
                    <span className="text-xs font-medium">{dimension.label}</span>
                  </div>
                  <span className="text-xs text-muted">{dimension.approved}/{dimension.total}</span>
                </div>
                <Progress
                  className="mt-3"
                  value={dimension.total ? (dimension.approved / dimension.total) * 100 : 0}
                  tone={dimension.approved ? "success" : "primary"}
                />
                <div className="mt-3 space-y-1.5">
                  {dimension.statement_samples.length ? (
                    dimension.statement_samples.map((statement, index) => (
                      <div key={`${dimension.dimension}-${index}`} className="flex items-start gap-2 text-xs leading-6">
                        <Quote className="mt-1 h-3 w-3 shrink-0 text-muted/60" />
                        <span>{statement}</span>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-muted">暂无已批准样本。</p>
                  )}
                </div>
                <p className="mt-3 text-[10px] text-muted">{dimension.evidence_count} 条证据关联</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>冲突与不确定性</CardTitle>
            <CardDescription>冲突不会被自动平均；保留上下文与人工判断</CardDescription>
          </div>
          <Badge tone={openConflicts.length ? "warning" : "success"}>{openConflicts.length} 待处理</Badge>
        </CardHeader>
        <CardContent className="pt-0">
          {conflicts.isLoading ? (
            <div className="flex h-24 items-center justify-center"><Spinner /></div>
          ) : !conflicts.data?.length ? (
            <EmptyState
              icon={<CircleDot className="h-5 w-5" />}
              title="没有检测到冲突"
              description="冲突检测基于同维度断言的语义重叠与否定/对立表达；运行蒸馏后会自动生成候选。"
            />
          ) : (
            <div className="space-y-2">
              {conflicts.data.map((conflict) => (
                <div key={conflict.id} className="rounded-xl border p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-warning" />
                      <span className="text-xs font-semibold">潜在冲突</span>
                      <StatusBadge status={conflict.status} />
                    </div>
                    <span className="text-[10px] text-muted">{relativeTime(conflict.created_at)}</span>
                  </div>
                  <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-muted">{conflict.description}</p>
                  {conflict.status === "open" ? (
                    <div className="mt-3 flex gap-2">
                      <Button size="sm" variant="primary" loading={resolve.isPending} onClick={() => resolve.mutate({ id: conflict.id, status: "resolved" })}>
                        保留并解决
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => resolve.mutate({ id: conflict.id, status: "ignored" })}>
                        忽略
                      </Button>
                    </div>
                  ) : conflict.resolution ? (
                    <p className="mt-2 text-[11px] text-muted">处理备注：{conflict.resolution}</p>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  tone: "success" | "warning" | "danger" | "primary";
}) {
  const colors = {
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    danger: "bg-danger/10 text-danger",
    primary: "bg-primary/10 text-primary",
  };
  return (
    <Card className="flex items-center gap-3 p-4">
      <div className={`rounded-xl p-2 ${colors[tone]}`}>{icon}</div>
      <div>
        <p className="text-[10px] uppercase tracking-wider text-muted">{label}</p>
        <p className="text-xl font-semibold">{value}</p>
      </div>
    </Card>
  );
}
