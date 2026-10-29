import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CheckCheck,
  ClipboardCheck,
  FileText,
  Filter,
  Quote,
  Search,
  X,
} from "lucide-react";
import { api } from "../../api";
import type { Claim } from "../../types";
import type { ProjectTabProps } from "../ProjectWorkspace";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DimensionBadge,
  EmptyState,
  Input,
  Select,
  Spinner,
  StatusBadge,
  Textarea,
  useToast,
} from "../../ui";
import { evidenceGradeLabels } from "../../lib/labels";
import { truncate } from "../../lib/format";

const dimensionOptions = [
  { value: "", label: "全部维度" },
  { value: "professional", label: "专业能力" },
  { value: "decision", label: "思维决策" },
  { value: "workflow", label: "工作流" },
  { value: "style", label: "表达风格" },
  { value: "boundary", label: "边界" },
  { value: "knowledge", label: "知识" },
];

export function ReviewTab({ project, setTab }: ProjectTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState("proposed");
  const [dimension, setDimension] = useState("");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statement, setStatement] = useState("");
  const [reason, setReason] = useState("");

  const claims = useQuery({
    queryKey: ["claims", project.id, status, dimension],
    queryFn: () => api.claims(project.id, { status: status || undefined, dimension: dimension || undefined }),
  });
  const sources = useQuery({ queryKey: ["sources", project.id], queryFn: () => api.sources(project.id) });
  const sourceMap = useMemo(
    () => new Map((sources.data || []).map((source) => [source.id, source])),
    [sources.data],
  );
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return claims.data || [];
    return (claims.data || []).filter((claim) =>
      [claim.statement, ...claim.evidence.map((item) => item.quote)].some((value) =>
        value.toLowerCase().includes(query),
      ),
    );
  }, [claims.data, search]);
  const selected = filtered.find((claim) => claim.id === selectedId) || filtered[0];

  useEffect(() => {
    if (!selectedId && filtered.length) setSelectedId(filtered[0].id);
  }, [filtered, selectedId]);
  useEffect(() => {
    if (selected) {
      setStatement(selected.statement);
      setReason(selected.review_reason || "");
    }
  }, [selected?.id]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["claims", project.id] });
    queryClient.invalidateQueries({ queryKey: ["persona", project.id] });
    queryClient.invalidateQueries({ queryKey: ["project", project.id] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const update = useMutation({
    mutationFn: (payload: { status?: string; statement?: string; reason?: string }) =>
      api.updateClaim(selected!.id, {
        status: payload.status,
        statement: payload.statement,
        review_reason: payload.reason,
      }),
    onSuccess: () => {
      refresh();
      toast({ title: "审核已保存", variant: "success" });
    },
    onError: (error: Error) => toast({ title: "保存失败", description: error.message, variant: "error" }),
  });

  const bulk = useMutation({
    mutationFn: () => {
      const ids = (claims.data || []).filter((claim) => claim.status === "proposed").map((claim) => claim.id);
      return api.bulkReview(project.id, ids, "approved", "批量批准待审核断言");
    },
    onSuccess: (result) => {
      refresh();
      toast({ title: `已批准 ${result.updated} 条断言`, variant: "success" });
    },
    onError: (error: Error) => toast({ title: "批量审批失败", description: error.message, variant: "error" }),
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="relative w-72">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input className="pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索断言或原文…" />
          </div>
          <label className="w-40">
            <span className="label">审核状态</span>
            <Select value={status} onChange={(event) => { setStatus(event.target.value); setSelectedId(null); }}>
              <option value="proposed">待审核</option>
              <option value="approved">已批准</option>
              <option value="rejected">已驳回</option>
              <option value="">全部状态</option>
            </Select>
          </label>
          <label className="w-40">
            <span className="label">维度</span>
            <Select value={dimension} onChange={(event) => { setDimension(event.target.value); setSelectedId(null); }}>
              {dimensionOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </Select>
          </label>
          <div className="ml-auto flex items-center gap-2">
            <Badge tone="neutral">{filtered.length} 条</Badge>
            <Button
              variant="primary"
              loading={bulk.isPending}
              disabled={!claims.data?.some((claim) => claim.status === "proposed")}
              onClick={() => bulk.mutate()}
            >
              <CheckCheck className="h-4 w-4" />
              批准全部待审
            </Button>
          </div>
        </CardContent>
      </Card>

      {claims.isLoading ? (
        <div className="flex h-64 items-center justify-center"><Spinner /></div>
      ) : !filtered.length ? (
        <Card>
          <EmptyState
            icon={<ClipboardCheck className="h-5 w-5" />}
            title={status === "proposed" ? "没有待审核断言" : "没有匹配的断言"}
            description={
              status === "proposed"
                ? "先运行蒸馏任务；或在其他状态筛选下查看已批准的断言。"
                : "调整筛选条件或清空搜索。"
            }
            action={
              status === "proposed" ? (
                <Button variant="primary" onClick={() => setTab("pipeline")}>去运行蒸馏</Button>
              ) : null
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[400px_1fr]">
          <Card className="max-h-[760px] overflow-auto">
            <CardHeader className="sticky top-0 z-10 border-b bg-surface">
              <div>
                <CardTitle>审核收件箱</CardTitle>
                <p className="mt-1 text-[11px] text-muted">按证据逐条批准、驳回或修订</p>
              </div>
              <Filter className="h-4 w-4 text-muted" />
            </CardHeader>
            <div className="divide-y">
              {filtered.map((claim) => (
                <button
                  key={claim.id}
                  type="button"
                  onClick={() => setSelectedId(claim.id)}
                  className={`w-full px-4 py-3 text-left transition ${selected?.id === claim.id ? "bg-primary/5" : "hover:bg-elevated"}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <DimensionBadge dimension={claim.dimension} />
                    <StatusBadge status={claim.status} />
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs leading-5">{claim.statement}</p>
                  <div className="mt-2 flex items-center gap-2 text-[10px] text-muted">
                    <span className="inline-flex items-center gap-1"><Quote className="h-3 w-3" />{claim.evidence.length} 条证据</span>
                    <span>·</span>
                    <span>{Math.round(claim.confidence * 100)}%</span>
                    <span>·</span>
                    <span>{evidenceGradeLabels[claim.evidence_grade] || claim.evidence_grade}</span>
                  </div>
                </button>
              ))}
            </div>
          </Card>

          <ClaimDetail
            claim={selected!}
            statement={statement}
            setStatement={setStatement}
            reason={reason}
            setReason={setReason}
            sourceMap={sourceMap}
            saving={update.isPending}
            onSave={(nextStatus) =>
              update.mutate({ status: nextStatus, statement: statement !== selected!.statement ? statement : undefined, reason })
            }
          />
        </div>
      )}
    </div>
  );
}

function ClaimDetail({
  claim,
  statement,
  setStatement,
  reason,
  setReason,
  sourceMap,
  saving,
  onSave,
}: {
  claim: Claim;
  statement: string;
  setStatement: (value: string) => void;
  reason: string;
  setReason: (value: string) => void;
  sourceMap: Map<string, any>;
  saving: boolean;
  onSave: (status?: string) => void;
}) {
  return (
    <Card className="max-h-[760px] overflow-auto">
      <CardHeader className="border-b">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <DimensionBadge dimension={claim.dimension} />
            <StatusBadge status={claim.status} />
            <Badge tone={claim.evidence_grade === "direct_quote" ? "success" : "warning"}>
              {evidenceGradeLabels[claim.evidence_grade] || claim.evidence_grade}
            </Badge>
            <Badge tone="neutral">{claim.claim_type}</Badge>
          </div>
          <p className="mt-2 text-[11px] text-muted">
            置信度 {Math.round(claim.confidence * 100)}% · {claim.evidence.length} 条证据 · 来源 {claim.source_count}
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-5">
        <label className="block">
          <span className="label">断言陈述（可人工修订）</span>
          <Textarea value={statement} onChange={(event) => setStatement(event.target.value)} className="min-h-[92px]" />
        </label>

        <div>
          <p className="mb-2 text-xs font-semibold">证据</p>
          {claim.evidence.length ? (
            <div className="space-y-2">
              {claim.evidence.map((evidence) => {
                const source = sourceMap.get(evidence.source_id);
                return (
                  <div key={evidence.id} className="rounded-xl border bg-elevated/40 p-3.5">
                    <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted">
                      <FileText className="h-3 w-3" />
                      <span>{source?.original_name || evidence.source_id}</span>
                      {evidence.page ? <span>第 {evidence.page} 页</span> : null}
                      {evidence.heading ? <span>{truncate(evidence.heading, 40)}</span> : null}
                      <span className="font-mono">{evidence.start_char}-{evidence.end_char}</span>
                    </div>
                    <p className="mt-2 border-l-2 border-primary/40 pl-3 text-xs leading-6">
                      “{evidence.quote}”
                    </p>
                  </div>
                );
              })}
            </div>
          ) : (
            <Alert tone="warning" title="没有可定位的证据">
              该断言可能是模型推断，或原文引用未能在文本块中定位。建议驳回，或补充来源后重新蒸馏。
            </Alert>
          )}
        </div>

        <label className="block">
          <span className="label">审核备注</span>
          <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="记录批准/驳回原因，便于审计" />
        </label>

        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button variant="primary" loading={saving} onClick={() => onSave("approved")}>
            <Check className="h-4 w-4" /> 批准断言
          </Button>
          <Button variant="danger" loading={saving} onClick={() => onSave("rejected")}>
            <X className="h-4 w-4" /> 驳回
          </Button>
          <Button variant="secondary" loading={saving} onClick={() => onSave(undefined)}>
            仅保存修订
          </Button>
          <span className="ml-auto text-[10px] text-muted">批准后才会进入 Skills 编译</span>
        </div>
      </CardContent>
    </Card>
  );
}
