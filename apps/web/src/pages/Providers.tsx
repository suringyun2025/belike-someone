import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  Server,
  ShieldCheck,
  Trash2,
  Zap,
} from "lucide-react";
import { api } from "../api";
import type { Protocol, Provider, ProviderTestResult } from "../types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  Textarea,
  useToast,
} from "../ui";
import { protocolLabels } from "../lib/labels";
import { formatDate } from "../lib/format";

const defaults: Record<Protocol, { base_url: string; api_version: string }> = {
  openai_responses: { base_url: "https://api.openai.com/v1", api_version: "" },
  openai_chat: { base_url: "https://api.openai.com/v1", api_version: "" },
  anthropic: { base_url: "https://api.anthropic.com/v1", api_version: "2023-06-01" },
  gemini: { base_url: "https://generativelanguage.googleapis.com/v1beta", api_version: "" },
};

interface FormState {
  name: string;
  protocol: Protocol;
  base_url: string;
  model_id: string;
  api_version: string;
  api_key: string;
  temperature: string;
  top_p: string;
  max_output_tokens: string;
  top_k: string;
  extra_headers: string;
  extra_body: string;
  enabled: boolean;
}

const emptyForm: FormState = {
  name: "",
  protocol: "openai_responses",
  base_url: defaults.openai_responses.base_url,
  model_id: "",
  api_version: "",
  api_key: "",
  temperature: "0.2",
  top_p: "0.9",
  max_output_tokens: "4096",
  top_k: "",
  extra_headers: "{}",
  extra_body: "{}",
  enabled: true,
};

export function ProvidersPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [testResult, setTestResult] = useState<Record<string, ProviderTestResult>>({});
  const [deleteTarget, setDeleteTarget] = useState<Provider | null>(null);

  const protocolMeta = useMemo(
    () => new Map((meta.data?.protocols || []).map((item) => [item.value, item])),
    [meta.data],
  );

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setOpen(true);
  };
  const openEdit = (provider: Provider) => {
    setEditing(provider);
    setForm({
      name: provider.name,
      protocol: provider.protocol,
      base_url: provider.base_url,
      model_id: provider.model_id,
      api_version: provider.api_version,
      api_key: "",
      temperature: String(provider.params?.temperature ?? ""),
      top_p: String(provider.params?.top_p ?? ""),
      max_output_tokens: String(provider.params?.max_output_tokens ?? ""),
      top_k: String(provider.params?.top_k ?? ""),
      extra_headers: JSON.stringify(provider.params?.extra_headers ?? {}, null, 2),
      extra_body: JSON.stringify(provider.params?.extra_body ?? {}, null, 2),
      enabled: provider.enabled,
    });
    setOpen(true);
  };

  const save = useMutation({
    mutationFn: () => {
      let extraHeaders: unknown;
      let extraBody: unknown;
      try {
        extraHeaders = JSON.parse(form.extra_headers || "{}");
        extraBody = JSON.parse(form.extra_body || "{}");
      } catch {
        throw new Error("高级参数必须是合法 JSON");
      }
      const params: Record<string, unknown> = {
        extra_headers: extraHeaders,
        extra_body: extraBody,
      };
      if (form.temperature.trim()) params.temperature = Number(form.temperature);
      if (form.top_p.trim()) params.top_p = Number(form.top_p);
      if (form.max_output_tokens.trim()) params.max_output_tokens = Number(form.max_output_tokens);
      if (form.top_k.trim()) params.top_k = Number(form.top_k);
      const payload = {
        name: form.name,
        protocol: form.protocol,
        base_url: form.base_url,
        model_id: form.model_id,
        api_version: form.api_version,
        params,
        enabled: form.enabled,
        ...(form.api_key.trim() ? { api_key: form.api_key.trim() } : {}),
      };
      return editing ? api.updateProvider(editing.id, payload) : api.createProvider(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["providers"] });
      setOpen(false);
      toast({ title: editing ? "模型配置已更新" : "模型配置已创建", variant: "success" });
    },
    onError: (error: Error) => toast({ title: "保存失败", description: error.message, variant: "error" }),
  });

  const test = useMutation({
    mutationFn: ({ id, jsonMode }: { id: string; jsonMode: boolean }) => api.testProvider(id, jsonMode),
    onSuccess: (result, variables) => {
      setTestResult((current) => ({ ...current, [variables.id]: result }));
      queryClient.invalidateQueries({ queryKey: ["providers"] });
      toast({
        title: result.ok ? "连接成功" : "连接失败",
        description: result.ok
          ? `${result.model} · ${result.latency_ms} ms`
          : `${result.error_code}: ${result.error_message}`,
        variant: result.ok ? "success" : "error",
      });
    },
    onError: (error: Error) => toast({ title: "测试失败", description: error.message, variant: "error" }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["providers"] });
      setDeleteTarget(null);
      toast({ title: "模型配置已删除", variant: "success" });
    },
    onError: (error: Error) => toast({ title: "删除失败", description: error.message, variant: "error" }),
  });

  const capabilities = protocolMeta.get(form.protocol)?.capabilities || {};

  return (
    <div className="mx-auto max-w-[1400px] animate-in">
      <PageHeader
        eyebrow="模型与 API"
        title="把模型接入蒸馏流水线"
        description="按协议分别适配 OpenAI Responses、Anthropic Messages 与 Gemini generateContent；OpenAI 兼容端点可切换到 Chat Completions 形态。密钥加密保存，前端只显示掩码。"
        actions={
          <Button variant="primary" onClick={openCreate}>
            <Plus className="h-4 w-4" />
            新增模型配置
          </Button>
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <ProtocolInfo title="OpenAI Responses" text="主协议；支持 instructions、text.format JSON Schema、推理参数与流式事件。" />
        <ProtocolInfo title="Anthropic Messages" text="system 与 messages 分离；max_tokens 必填；JSON Schema 通过 forced tool use。" />
        <ProtocolInfo title="Gemini generateContent" text="contents/parts 与 generationConfig；responseSchema 是 OpenAPI 子集。" />
      </div>

      {providers.isLoading ? (
        <div className="flex h-48 items-center justify-center"><Spinner /></div>
      ) : !providers.data?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center py-14 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Server className="h-5 w-5" />
            </div>
            <h3 className="mt-3 text-sm font-semibold">还没有模型配置</h3>
            <p className="mt-1 max-w-md text-xs leading-6 text-muted">
              不配置也能使用离线启发式蒸馏；配置模型后可获得更好的断言抽取、冲突判断与行为评测。
            </p>
            <Button className="mt-4" variant="primary" onClick={openCreate}>
              <Plus className="h-4 w-4" />
              新增模型配置
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {providers.data.map((provider) => {
            const result = testResult[provider.id];
            const isTesting = test.isPending && test.variables?.id === provider.id;
            return (
              <Card key={provider.id} className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      <Server className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-sm font-semibold">{provider.name}</h3>
                        <Badge tone="primary">{protocolLabels[provider.protocol] || provider.protocol}</Badge>
                        <StatusBadge status={provider.last_test_status} />
                      </div>
                      <p className="mt-1 truncate font-mono text-[10px] text-muted">{provider.base_url}</p>
                      <p className="mt-0.5 truncate text-xs text-muted">Model: {provider.model_id}</p>
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button size="sm" variant="ghost" onClick={() => openEdit(provider)}><Pencil className="h-3.5 w-3.5" /></Button>
                    <Button size="sm" variant="ghost" onClick={() => setDeleteTarget(provider)}><Trash2 className="h-3.5 w-3.5 text-danger" /></Button>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-1.5">
                  <Capability active={Boolean(capabilities.json_schema)}>JSON Schema</Capability>
                  <Capability active={Boolean(capabilities.streaming)}>流式</Capability>
                  <Capability active={Boolean(capabilities.tools)}>工具调用</Capability>
                  <Capability active={Boolean(capabilities.top_k)}>top_k</Capability>
                  <Capability active={Boolean(capabilities.cache_usage)}>缓存用量</Capability>
                </div>

                <div className="mt-4 grid grid-cols-1 gap-2 rounded-xl border bg-elevated/40 p-3 text-[11px] sm:grid-cols-3">
                  <div><p className="text-muted">温度</p><p className="mt-0.5 font-mono">{String(provider.params?.temperature ?? "—")}</p></div>
                  <div><p className="text-muted">top_p</p><p className="mt-0.5 font-mono">{String(provider.params?.top_p ?? "—")}</p></div>
                  <div><p className="text-muted">max tokens</p><p className="mt-0.5 font-mono">{String(provider.params?.max_output_tokens ?? "—")}</p></div>
                </div>

                {provider.last_test_error || result?.error_message ? (
                  <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-5 text-danger">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    {result?.error_message || provider.last_test_error}
                  </p>
                ) : null}
                {result?.ok ? (
                  <p className="mt-3 flex items-center gap-1.5 text-[11px] text-success">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    {result.model} · {result.latency_ms} ms · {result.text.slice(0, 40)}
                  </p>
                ) : null}

                <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t pt-3">
                  <span className="flex items-center gap-1.5 text-[10px] text-muted">
                    <KeyRound className="h-3 w-3" />
                    {provider.has_api_key ? provider.api_key_mask : "未设置 API Key"}
                  </span>
                  <div className="flex gap-2">
                    <Button size="sm" variant="secondary" loading={isTesting} onClick={() => test.mutate({ id: provider.id, jsonMode: false })}>
                      <Zap className="h-3.5 w-3.5" />
                      测试连接
                    </Button>
                    <Button size="sm" variant="ghost" loading={isTesting} onClick={() => test.mutate({ id: provider.id, jsonMode: true })}>
                      测试 JSON
                    </Button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <Alert tone="info" className="mt-5" title="协议与参数边界">
        不同端点对参数支持不一致。平台会按协议能力矩阵提示不支持项；OpenAI 兼容端点（DeepSeek、Qwen、vLLM、Ollama 等）通常只实现 Chat Completions，请在 OpenAI 协议下切换 API 形态。
      </Alert>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={editing ? "编辑模型配置" : "新增模型配置"}
        description="配置会保存为可复用的 Provider；每个流水线阶段可以单独指定它。"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
            <Button
              variant="primary"
              loading={save.isPending}
              disabled={!form.name.trim() || !form.model_id.trim() || !form.base_url.trim()}
              onClick={() => save.mutate()}
            >
              保存配置
            </Button>
          </>
        }
      >
        <div className="space-y-5">
          <div>
            <p className="mb-2 text-xs font-semibold">协议</p>
            <div className="grid grid-cols-2 gap-2">
              {(Object.keys(protocolLabels) as Protocol[]).map((protocol) => (
                <button
                  key={protocol}
                  type="button"
                  onClick={() =>
                    setForm((current) => ({
                      ...current,
                      protocol,
                      base_url: defaults[protocol].base_url,
                      api_version: defaults[protocol].api_version,
                    }))
                  }
                  className={`rounded-xl border p-3 text-left transition ${
                    form.protocol === protocol ? "border-primary/40 bg-primary/5" : "hover:bg-elevated"
                  }`}
                >
                  <p className="text-xs font-medium">{protocolLabels[protocol]}</p>
                  <p className="mt-1 text-[10px] leading-4 text-muted">
                    {protocol === "openai_responses"
                      ? "主协议 / 官方 OpenAI"
                      : protocol === "openai_chat"
                        ? "兼容端点 / 旧接口"
                        : protocol === "anthropic"
                          ? "Claude / Messages"
                          : "Gemini / generateContent"}
                  </p>
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="显示名称" required>
              <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：OpenAI 主模型" />
            </Field>
            <Field label="Model ID" required>
              <Input value={form.model_id} onChange={(event) => setForm({ ...form, model_id: event.target.value })} placeholder="填写供应商支持的模型 ID" />
            </Field>
          </div>
          <Field label="Base URL" required hint="可以包含 /v1 或 /v1beta；没有版本段时平台会按协议补全。">
            <Input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://api.openai.com/v1" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="API Key" hint={editing ? "留空表示保留现有密钥；密钥不会回显。" : "加密保存在本地数据目录。"}>
              <Input type="password" value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} placeholder={editing ? "留空保持不变" : "sk-..."} />
            </Field>
            <Field label="API Version" hint="Anthropic 默认 2023-06-01；其他协议可留空。">
              <Input value={form.api_version} onChange={(event) => setForm({ ...form, api_version: event.target.value })} placeholder="2023-06-01" />
            </Field>
          </div>

          <div>
            <p className="mb-2 text-xs font-semibold">常用参数</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field label="temperature">
                <Input value={form.temperature} onChange={(event) => setForm({ ...form, temperature: event.target.value })} placeholder="0.2" />
              </Field>
              <Field label="top_p">
                <Input value={form.top_p} onChange={(event) => setForm({ ...form, top_p: event.target.value })} placeholder="0.9" />
              </Field>
              <Field label="max tokens">
                <Input value={form.max_output_tokens} onChange={(event) => setForm({ ...form, max_output_tokens: event.target.value })} placeholder="4096" />
              </Field>
              <Field label="top_k" hint={capabilities.top_k ? "该协议支持" : "该协议不支持"}>
                <Input value={form.top_k} onChange={(event) => setForm({ ...form, top_k: event.target.value })} placeholder="—" disabled={!capabilities.top_k} />
              </Field>
            </div>
          </div>

          <div>
            <p className="mb-2 text-xs font-semibold">高级参数（JSON）</p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="extra_headers">
                <Textarea className="min-h-[90px] font-mono text-xs" value={form.extra_headers} onChange={(event) => setForm({ ...form, extra_headers: event.target.value })} />
              </Field>
              <Field label="extra_body">
                <Textarea className="min-h-[90px] font-mono text-xs" value={form.extra_body} onChange={(event) => setForm({ ...form, extra_body: event.target.value })} />
              </Field>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-muted">
              <input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} className="h-4 w-4 accent-[hsl(var(--primary))]" />
              启用该配置
            </label>
            {capabilities.notes ? (
              <p className="text-[10px] text-muted">{capabilities.notes.join("；")}</p>
            ) : null}
          </div>
        </div>
      </Modal>

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="删除模型配置？"
        description="使用该配置的项目会自动解除绑定；不会删除已经生成的任务或 Skills。"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => deleteTarget && remove.mutate(deleteTarget.id)}>删除</Button>
          </>
        }
      >
        <Alert tone="warning">{deleteTarget?.name} · {deleteTarget?.model_id}</Alert>
      </Modal>
    </div>
  );
}

function ProtocolInfo({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-xl border bg-surface p-3.5">
      <p className="text-xs font-semibold">{title}</p>
      <p className="mt-1 text-[11px] leading-5 text-muted">{text}</p>
    </div>
  );
}

function Capability({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${active ? "border-success/20 bg-success/10 text-success" : "border-border bg-elevated text-muted/60 line-through"}`}>
      {active ? <CheckCircle2 className="h-2.5 w-2.5" /> : <Loader2 className="h-2.5 w-2.5" />}
      {children}
    </span>
  );
}
