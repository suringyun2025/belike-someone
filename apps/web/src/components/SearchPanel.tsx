import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseZap, RefreshCw, Search } from "lucide-react";
import { api } from "../api";
import type { SearchResponse } from "../types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Spinner,
  useToast,
} from "../ui";
import { truncate } from "../lib/format";

export function SearchPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const status = useQuery({
    queryKey: ["vector-status", projectId],
    queryFn: () => api.vectorStatus(projectId),
  });
  const search = useMutation({
    mutationFn: () => api.search(projectId, query),
    onSuccess: setResponse,
    onError: (error: Error) => toast({ title: "检索失败", description: error.message, variant: "error" }),
  });
  const index = useMutation({
    mutationFn: () => api.indexProject(projectId, true),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["vector-status", projectId] });
      toast({
        title: "向量索引已重建",
        description: `${result.indexed} 个文本块 · ${result.backend} · ${result.vec ? "sqlite-vec" : "余弦兜底"}`,
        variant: "success",
      });
      if (query.trim()) search.mutate();
    },
    onError: (error: Error) => toast({ title: "索引失败", description: error.message, variant: "error" }),
  });

  const backendLabel =
    status.data?.backend === "fastembed" ? "BGE 语义向量" : status.data?.backend === "hash-ngram" ? "哈希向量兜底" : "未初始化";

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>知识检索</CardTitle>
          <CardDescription>向量检索跨资料块定位事实与案例</CardDescription>
        </div>
        <Badge tone={status.data?.backend === "fastembed" ? "success" : "warning"}>{backendLabel}</Badge>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (query.trim()) search.mutate();
          }}
        >
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-9"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="例如：性能测量、冒充声明、代码评审…"
            />
          </div>
          <Button type="submit" variant="primary" loading={search.isPending} disabled={!query.trim()}>
            检索
          </Button>
        </form>

        <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-muted">
          <span>
            {status.data
              ? `${status.data.embedded}/${status.data.chunks} 块已索引 · ${status.data.dim} 维 · ${status.data.vec ? "sqlite-vec" : "余弦检索"}`
              : "索引状态加载中…"}
          </span>
          <Button
            size="sm"
            variant="ghost"
            loading={index.isPending}
            onClick={() => index.mutate()}
            title="重新计算全部文本块的向量"
          >
            <RefreshCw className="h-3 w-3" />
            重建索引
          </Button>
        </div>

        {status.data?.warning ? (
          <Alert tone="warning">{truncate(status.data.warning, 220)}</Alert>
        ) : null}

        {search.isPending ? (
          <div className="flex h-20 items-center justify-center"><Spinner /></div>
        ) : response ? (
          response.results.length ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[10px] text-muted">
                <Badge tone="info">{response.mode}</Badge>
                {response.warning ? <span className="truncate">{response.warning}</span> : null}
              </div>
              {response.results.map((result) => (
                <div key={result.chunk_id} className="rounded-xl border bg-elevated/30 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-muted">
                    <span className="flex items-center gap-1.5">
                      <DatabaseZap className="h-3 w-3" />
                      {result.source_name}
                      {result.page_start ? ` · 第 ${result.page_start} 页` : ""}
                      {result.heading_path ? ` · ${truncate(result.heading_path, 30)}` : ""}
                    </span>
                    {result.score !== null ? <span className="font-mono">{result.score.toFixed(3)}</span> : null}
                  </div>
                  <p className="mt-2 line-clamp-3 text-xs leading-5">{truncate(result.text, 260)}</p>
                </div>
              ))}
            </div>
          ) : (
            <Alert tone="info">没有检索到相关内容。资料变更后请重建索引。</Alert>
          )
        ) : (
          <p className="rounded-xl border border-dashed px-3 py-4 text-center text-[11px] text-muted">
            索引完成后可在这里验证语义检索；当前示例项目可在资料库添加更多资料。
          </p>
        )}
      </CardContent>
    </Card>
  );
}
