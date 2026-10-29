import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Eye,
  FileArchive,
  FileText,
  RefreshCw,
  Shield,
  Trash2,
  Upload,
} from "lucide-react";
import { api } from "../../api";
import type { Source } from "../../types";
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
  Modal,
  Spinner,
  StatusBadge,
  useToast,
} from "../../ui";
import { formatBytes, formatDate, truncate } from "../../lib/format";
import { sourceTypeLabels } from "../../lib/labels";

export function SourcesTab({ project }: ProjectTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Source | null>(null);
  const sources = useQuery({ queryKey: ["sources", project.id], queryFn: () => api.sources(project.id) });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["sources", project.id] });
    queryClient.invalidateQueries({ queryKey: ["project", project.id] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const upload = useMutation({
    mutationFn: (files: FileList | File[]) => api.uploadSources(project.id, files),
    onSuccess: (items) => {
      refresh();
      const flagged = items.filter((item) => ["needs_ocr", "needs_asr", "failed"].includes(item.status));
      toast({
        title: `已导入 ${items.length} 份资料`,
        description: flagged.length
          ? `${flagged.length} 份需要 OCR/ASR 或解析失败，请查看状态。`
          : "解析与分块已完成，可以开始蒸馏。",
        variant: flagged.length ? "info" : "success",
      });
    },
    onError: (error: Error) => toast({ title: "导入失败", description: error.message, variant: "error" }),
  });

  const reparse = useMutation({
    mutationFn: (sourceId: string) => api.reparseSource(sourceId),
    onSuccess: () => {
      refresh();
      toast({ title: "已重新解析", variant: "success" });
    },
    onError: (error: Error) => toast({ title: "解析失败", description: error.message, variant: "error" }),
  });

  const remove = useMutation({
    mutationFn: (sourceId: string) => api.deleteSource(sourceId),
    onSuccess: () => {
      refresh();
      setDeleteTarget(null);
      toast({ title: "资料已删除", variant: "success" });
    },
    onError: (error: Error) => toast({ title: "删除失败", description: error.message, variant: "error" }),
  });

  const stats = useMemo(() => {
    const items = sources.data || [];
    return {
      parsed: items.filter((item) => item.status === "parsed").length,
      pending: items.filter((item) => !["parsed", "failed"].includes(item.status)).length,
      failed: items.filter((item) => item.status === "failed").length,
      chunks: items.reduce((sum, item) => sum + item.chunk_count, 0),
    };
  }, [sources.data]);

  return (
    <div className="space-y-5">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (event.dataTransfer.files.length) upload.mutate(event.dataTransfer.files);
        }}
        className={`relative overflow-hidden rounded-2xl border-2 border-dashed p-8 text-center transition ${
          dragging ? "border-primary bg-primary/5" : "border-border bg-surface"
        }`}
      >
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <Upload className="h-5 w-5" />
        </div>
        <h3 className="mt-3 text-sm font-semibold">拖入资料，或从本机选择文件</h3>
        <p className="mx-auto mt-1.5 max-w-xl text-xs leading-5 text-muted">
          支持 PDF、DOCX、XLSX、Markdown、TXT、HTML、CSV、JSON/JSONL、聊天记录、代码与 ZIP。
          扫描 PDF 与音视频需要安装可选 OCR/ASR 依赖。原始文件只保存在本地。
        </p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <Button variant="primary" loading={upload.isPending} onClick={() => inputRef.current?.click()}>
            <Upload className="h-4 w-4" />
            选择文件
          </Button>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(event) => {
              const selected = event.target.files ? Array.from(event.target.files) : [];
              event.target.value = "";
              if (selected.length) upload.mutate(selected);
            }}
          />
          <span className="text-[11px] text-muted">单文件上限 256 MB</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MiniStat label="已解析" value={stats.parsed} />
        <MiniStat label="待处理" value={stats.pending} />
        <MiniStat label="失败" value={stats.failed} />
        <MiniStat label="文本块" value={stats.chunks} />
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>资料库</CardTitle>
            <CardDescription>去重按 SHA-256 标记，不自动删除；重复转载不计为独立证据</CardDescription>
          </div>
          <Button size="sm" variant="secondary" onClick={() => sources.refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </Button>
        </CardHeader>
        <CardContent className="pt-0">
          {sources.isLoading ? (
            <div className="flex h-40 items-center justify-center"><Spinner /></div>
          ) : !sources.data?.length ? (
            <EmptyState
              icon={<FileText className="h-5 w-5" />}
              title="资料库为空"
              description="上传访谈、文章、聊天记录、代码或扫描件。ZIP 会安全解压并逐个导入。"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>文件</th>
                    <th>类型</th>
                    <th>状态</th>
                    <th>分块</th>
                    <th>大小</th>
                    <th>脱敏</th>
                    <th className="text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.data.map((source) => (
                    <tr key={source.id}>
                      <td>
                        <div className="flex items-start gap-2.5">
                          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-elevated text-muted">
                            {source.original_name.toLowerCase().endsWith(".zip") ? (
                              <FileArchive className="h-4 w-4" />
                            ) : (
                              <FileText className="h-4 w-4" />
                            )}
                          </div>
                          <div className="min-w-0">
                            <p className="max-w-[320px] truncate text-xs font-medium">{source.original_name}</p>
                            <p className="mt-0.5 text-[10px] text-muted">{formatDate(source.created_at)}</p>
                            {source.parse_error ? (
                              <p className="mt-1 max-w-[320px] truncate text-[10px] text-danger">{source.parse_error}</p>
                            ) : null}
                          </div>
                          {source.duplicate_of ? <Badge tone="warning">重复</Badge> : null}
                        </div>
                      </td>
                      <td className="text-xs text-muted">{sourceTypeLabels[source.source_type] || source.source_type}</td>
                      <td><StatusBadge status={source.status} /></td>
                      <td className="font-mono text-xs">{source.chunk_count}</td>
                      <td className="text-xs text-muted">{formatBytes(source.size)}</td>
                      <td>
                        {source.redaction_count ? (
                          <span className="inline-flex items-center gap-1 text-[11px] text-warning">
                            <Shield className="h-3 w-3" />
                            {source.redaction_count}
                          </span>
                        ) : (
                          <span className="text-[11px] text-muted">—</span>
                        )}
                      </td>
                      <td>
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => setPreviewId(source.id)}>
                            <Eye className="h-3.5 w-3.5" />
                            预览
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={reparse.isPending}
                            onClick={() => reparse.mutate(source.id)}
                          >
                            <RefreshCw className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setDeleteTarget(source)}>
                            <Trash2 className="h-3.5 w-3.5 text-danger" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <PreviewModal sourceId={previewId} onClose={() => setPreviewId(null)} />
      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="删除资料？"
        description="这会删除该资料的解析结果与文本块，并可能使下游断言失去证据。原始文件也会从本地数据目录移除。"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={() => deleteTarget && remove.mutate(deleteTarget.id)}
            >
              删除资料
            </Button>
          </>
        }
      >
        <Alert tone="warning">
          {deleteTarget?.original_name} · {deleteTarget?.chunk_count} 个文本块
        </Alert>
      </Modal>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border bg-surface px-4 py-3">
      <p className="text-[10px] uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

function PreviewModal({ sourceId, onClose }: { sourceId: string | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const preview = useQuery({
    queryKey: ["source-preview", sourceId],
    queryFn: () => api.previewSource(sourceId!),
    enabled: Boolean(sourceId),
  });
  const chunks = useQuery({
    queryKey: ["source-chunks", sourceId],
    queryFn: () => api.sourceChunks(sourceId!),
    enabled: Boolean(sourceId),
  });
  const [mode, setMode] = useState<"blocks" | "chunks">("blocks");

  const toggle = useMutation({
    mutationFn: ({ chunkId, excluded }: { chunkId: string; excluded: boolean }) =>
      api.setChunkExcluded(chunkId, excluded),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["source-chunks", sourceId] });
      queryClient.invalidateQueries({ queryKey: ["vector-status"] });
      toast({
        title: result.excluded ? "已排除该文本块" : "已恢复该文本块",
        description: result.excluded ? "后续蒸馏不会再把它发给模型。" : undefined,
        variant: "success",
      });
    },
    onError: (error: Error) =>
      toast({ title: "操作失败", description: error.message, variant: "error" }),
  });

  return (
    <Modal
      open={Boolean(sourceId)}
      onClose={onClose}
      title={preview.data?.source.original_name || "资料预览"}
      description="左侧为解析块及其页码/标题定位；分块用于证据检索。敏感信息在解析阶段已做基础脱敏。"
      size="xl"
    >
      {preview.isLoading ? (
        <div className="flex h-48 items-center justify-center"><Spinner /></div>
      ) : preview.data ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={preview.data.source.status} />
            <Badge tone="neutral">{sourceTypeLabels[preview.data.source.source_type] || preview.data.source.source_type}</Badge>
            <Badge tone="neutral">{preview.data.blocks.length} 个解析块</Badge>
            <Badge tone="neutral">{chunks.data?.length || 0} 个文本块</Badge>
            {preview.data.source.redaction_count ? (
              <Badge tone="warning">脱敏 {preview.data.source.redaction_count} 处</Badge>
            ) : null}
          </div>
          {preview.data.source.parse_error ? (
            <Alert tone={preview.data.source.status === "failed" ? "danger" : "warning"} title="解析提示">
              {preview.data.source.parse_error}
            </Alert>
          ) : null}
          <div className="flex gap-1 rounded-xl bg-elevated p-1">
            <button
              type="button"
              onClick={() => setMode("blocks")}
              className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-medium ${mode === "blocks" ? "bg-surface shadow-sm" : "text-muted"}`}
            >
              解析块
            </button>
            <button
              type="button"
              onClick={() => setMode("chunks")}
              className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-medium ${mode === "chunks" ? "bg-surface shadow-sm" : "text-muted"}`}
            >
              文本块 / 证据单元
            </button>
          </div>
          {mode === "blocks" ? (
            <div className="space-y-2">
              {preview.data.blocks.map((block: any) => (
                <div key={block.id} className="rounded-xl border p-3">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[10px] text-muted">
                    <Badge tone="neutral">{block.kind}</Badge>
                    {block.page ? <span>第 {block.page} 页</span> : null}
                    {block.heading ? <span>{truncate(block.heading, 60)}</span> : null}
                    <span className="font-mono">{block.start_char}-{block.end_char}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-xs leading-6">{block.text}</p>
                </div>
              ))}
              {preview.data.truncated ? <Alert tone="info">仅显示前 300 个解析块。</Alert> : null}
            </div>
          ) : (
            <div className="space-y-2">
              {(chunks.data || []).map((chunk) => (
                <div
                  key={chunk.id}
                  className={`rounded-xl border p-3 ${chunk.excluded ? "border-dashed opacity-60" : ""}`}
                >
                  <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[10px] text-muted">
                    <span className="font-mono">#{chunk.order_index}</span>
                    <span>≈ {chunk.token_estimate} tokens</span>
                    {chunk.page_start ? <span>第 {chunk.page_start}{chunk.page_end && chunk.page_end !== chunk.page_start ? `-${chunk.page_end}` : ""} 页</span> : null}
                    {chunk.heading_path ? <span>{truncate(chunk.heading_path, 60)}</span> : null}
                    {chunk.excluded ? <Badge tone="neutral">已排除</Badge> : null}
                    <button
                      type="button"
                      disabled={toggle.isPending}
                      onClick={() =>
                        toggle.mutate({ chunkId: chunk.id, excluded: !chunk.excluded })
                      }
                      className="ml-auto rounded-md px-1.5 py-0.5 text-[10px] font-medium text-primary hover:bg-primary/10 disabled:opacity-50"
                    >
                      {chunk.excluded ? "恢复" : "排除"}
                    </button>
                  </div>
                  <p className="whitespace-pre-wrap text-xs leading-6 text-muted">{truncate(chunk.text, 700)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <Alert tone="danger" title="无法加载预览">
          {preview.error instanceof Error ? preview.error.message : "请重试。"}
        </Alert>
      )}
    </Modal>
  );
}
