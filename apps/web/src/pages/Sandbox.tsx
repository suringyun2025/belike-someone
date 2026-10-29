import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Clock,
  KeyRound,
  Loader2,
  Plug,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { SandboxTicket } from "../types";

const PROTOCOLS = [
  {
    value: "openai_chat",
    label: "OpenAI Chat Completions",
    hint: "兼容 DeepSeek / Qwen / 硅基流动 / vLLM / Ollama",
    placeholder: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
  },
  {
    value: "openai_responses",
    label: "OpenAI Responses",
    hint: "OpenAI 新版 Responses API",
    placeholder: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
  },
  {
    value: "anthropic",
    label: "Anthropic Messages",
    hint: "Claude 系列",
    placeholder: "https://api.anthropic.com/v1",
    model: "claude-3-5-haiku-latest",
  },
  {
    value: "gemini",
    label: "Google Gemini",
    hint: "generateContent",
    placeholder: "https://generativelanguage.googleapis.com/v1beta",
    model: "gemini-2.0-flash",
  },
] as const;

type Stage = "form" | "probing" | "queued" | "entering";

export function SandboxPage() {
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<Stage>("form");
  const [nickname, setNickname] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [protocol, setProtocol] = useState<string>("openai_chat");
  const [modelId, setModelId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const [ticket, setTicket] = useState<SandboxTicket | null>(null);
  const [fingerprint, setFingerprint] = useState("");
  const claimStarted = useRef(false);

  const state = useQuery({
    queryKey: ["sandbox-state"],
    queryFn: api.sandboxState,
    // The seat changes without this tab acting, so poll while waiting to enter.
    refetchInterval: stage === "form" ? 15_000 : false,
    retry: 0,
  });

  const busy = state.data?.state === "busy";
  const occupant = state.data?.occupant;

  const join = useMutation({
    mutationFn: () =>
      api.sandboxJoin({
        base_url: baseUrl.trim(),
        protocol: protocol as never,
        model_id: modelId.trim(),
        api_key: apiKey.trim(),
        nickname: nickname.trim(),
      }),
    onMutate: () => {
      setError("");
      setStage("probing");
    },
    onSuccess: (result) => {
      if (result.state === "active") {
        setStage("entering");
        queryClient.invalidateQueries();
        // A full reload is the simplest way to make every page refetch under the
        // new session; the SPA has no shared "session changed" event.
        window.location.href = "/";
        return;
      }
      setTicket(result.ticket || null);
      setFingerprint(result.ticket?.fingerprint || "");
      setStage("queued");
    },
    onError: (err: Error) => {
      setStage("form");
      setError(err instanceof ApiError && err.requestId ? `${err.message}` : err.message);
    },
  });

  // Poll the ticket while queued; claim the moment it is ready.
  const ticketQuery = useQuery({
    queryKey: ["sandbox-ticket", ticket?.ticket_id],
    queryFn: () => api.sandboxTicket(ticket!.ticket_id, fingerprint),
    enabled: stage === "queued" && Boolean(ticket?.ticket_id),
    refetchInterval: 4000,
    retry: 0,
  });

  useEffect(() => {
    if (stage !== "queued" || !ticket || claimStarted.current) return;
    const data = ticketQuery.data;
    if (!data) return;
    const fp = data.fingerprint || fingerprint;
    if (data.state === "active" || data.ticket?.claimable) {
      claimStarted.current = true;
      claimTicket(ticket.ticket_id, fp);
    }
  }, [stage, ticket, ticketQuery.data]);

  async function claimTicket(ticketId: string, fp: string) {
    setStage("entering");
    try {
      await api.sandboxClaim({ ticket_id: ticketId, fingerprint: fp });
      window.location.href = "/";
    } catch (err) {
      claimStarted.current = false;
      setStage("queued");
      setError(err instanceof Error ? err.message : "领取座位失败");
    }
  }

  const selected = PROTOCOLS.find((item) => item.value === protocol) || PROTOCOLS[0];
  const liveTicket = ticketQuery.data?.ticket;
  // Fall back to the value returned by the join call until the first poll lands.
  const position = liveTicket?.position ?? ticket?.position ?? 1;
  const queueTotal = position + (liveTicket?.ahead ?? ticket?.ahead ?? 0);
  const canSubmit =
    baseUrl.trim().length > 8 &&
    modelId.trim().length > 0 &&
    apiKey.trim().length >= 8 &&
    stage !== "probing";

  return (
    <div className="min-h-screen bg-bg">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-10 sm:px-6 lg:py-14">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="relative flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-fg shadow-sm">
              <Boxes className="h-6 w-6" />
              <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">蒸馏平台 · 公开体验</h1>
              <p className="text-[10px] uppercase tracking-[0.16em] text-muted">
                Persona Distillation Studio
              </p>
            </div>
          </div>
          <SeatBadge state={state.data?.state} occupant={occupant} waiting={state.data?.waiting ?? 0} />
        </header>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
          <section className="card p-6">
            {stage === "form" || stage === "probing" ? (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!canSubmit) return;
                  join.mutate();
                }}
              >
                <div>
                  <h2 className="text-base font-semibold tracking-tight">用你自己的模型 Key 体验</h2>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    {busy
                      ? "当前有人正在使用。你提交后会进入队列，轮到时会自动进入工作台。"
                      : "现在空着，填完即可进入。同一时刻只服务一个人，保证这台小服务器的稳定。"}
                  </p>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className="label">协议</span>
                    <select
                      className="input"
                      value={protocol}
                      onChange={(event) => {
                        setProtocol(event.target.value);
                        const next = PROTOCOLS.find((item) => item.value === event.target.value);
                        if (next && !modelId) setModelId(next.model);
                      }}
                    >
                      {PROTOCOLS.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                    <span className="mt-1 block text-[10px] leading-4 text-muted">{selected.hint}</span>
                  </label>

                  <label className="block">
                    <span className="label">称呼（可选）</span>
                    <input
                      className="input"
                      value={nickname}
                      onChange={(event) => setNickname(event.target.value)}
                      placeholder="显示在排队信息里"
                      maxLength={60}
                    />
                  </label>
                </div>

                <label className="block">
                  <span className="label">API Base URL</span>
                  <input
                    className="input font-mono text-xs"
                    value={baseUrl}
                    onChange={(event) => setBaseUrl(event.target.value)}
                    placeholder={selected.placeholder}
                    spellCheck={false}
                    required
                  />
                  <span className="mt-1 block text-[10px] leading-4 text-muted">
                    必须是公网地址；本机、内网与保留网段会被拒绝。
                  </span>
                </label>

                <label className="block">
                  <span className="label">模型 ID</span>
                  <input
                    className="input font-mono text-xs"
                    value={modelId}
                    onChange={(event) => setModelId(event.target.value)}
                    placeholder={selected.model}
                    spellCheck={false}
                    required
                  />
                </label>

                <label className="block">
                  <span className="label">API Key</span>
                  <div className="relative">
                    <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                    <input
                      className="input pl-9 font-mono text-xs"
                      type="password"
                      value={apiKey}
                      onChange={(event) => setApiKey(event.target.value)}
                      placeholder="sk-..."
                      autoComplete="off"
                      spellCheck={false}
                      required
                    />
                  </div>
                  <span className="mt-1 flex items-start gap-1 text-[10px] leading-4 text-muted">
                    <Trash2 className="mt-0.5 h-3 w-3 shrink-0" />
                    只用于这一次体验，结束或超时后连同你的资料一起从服务器删除。
                  </span>
                </label>

                {error ? (
                  <div className="flex items-start gap-2 rounded-xl border border-danger/25 bg-danger/5 px-3 py-2.5 text-xs leading-5 text-danger">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="break-all">{error}</span>
                  </div>
                ) : null}

                <button type="submit" disabled={!canSubmit} className="btn btn-primary btn-lg w-full">
                  {stage === "probing" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      正在验证你的端点…
                    </>
                  ) : (
                    <>
                      <Plug className="h-4 w-4" />
                      {busy ? "加入队列" : "验证并进入"}
                    </>
                  )}
                </button>
                <p className="text-center text-[10px] leading-4 text-muted">
                  提交时服务端会真实调用一次你的模型（约 1 次很小的请求）以确认可用。
                </p>
              </form>
            ) : null}

            {stage === "queued" && ticket ? (
              <div className="space-y-4">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <Clock className="h-4 w-4 text-primary" />
                  正在排队
                </div>
                <div className="rounded-xl border bg-elevated/50 p-5">
                  <div className="flex items-end gap-2">
                    <span className="text-4xl font-semibold tabular-nums">
                      {liveTicket?.position ?? ticket.position}
                    </span>
                    <span className="pb-1.5 text-xs text-muted">当前位次</span>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted">
                    前面还有 {liveTicket?.ahead ?? ticket.ahead} 人。预计等待约{" "}
                    {formatWait(liveTicket?.estimated_wait_seconds ?? ticket.estimated_wait_seconds)}。
                  </p>

                  {/* Progress makes the wait legible: a bare number with no scale
                      reads as "forever". The bar is the queue, filled up to the
                      visitor's place. */}
                  <div className="mt-4 space-y-1.5">
                    <div className="flex items-center justify-between text-[10px] text-muted">
                      <span>排队进度</span>
                      <span>
                        第 {position} 位 · 共 {queueTotal} 人
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-border">
                      <div
                        className="h-full rounded-full bg-primary transition-all"
                        style={{ width: `${Math.max(6, (1 / queueTotal) * 100)}%` }}
                      />
                    </div>
                  </div>

                  {liveTicket?.claimable ? (
                    <div className="mt-4 flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-[11px] text-success">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      轮到你了，正在进入工作台…
                    </div>
                  ) : (
                    <p className="mt-4 rounded-lg bg-bg/70 px-3 py-2 text-[11px] leading-5 text-muted">
                      轮到你时会自动进入工作台，这个页面不要关。若长时间没轮到，排队凭证会自动失效。
                    </p>
                  )}
                </div>
                {error ? (
                  <div className="flex items-start gap-2 rounded-xl border border-danger/25 bg-danger/5 px-3 py-2.5 text-xs leading-5 text-danger">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="break-all">{error}</span>
                  </div>
                ) : null}
                <button
                  type="button"
                  className="btn w-full"
                  onClick={() => {
                    setStage("form");
                    setTicket(null);
                    setError("");
                  }}
                >
                  取消排队
                </button>
              </div>
            ) : null}

            {stage === "entering" ? (
              <div className="flex flex-col items-center gap-3 py-16 text-sm text-muted">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
                正在准备工作台…
              </div>
            ) : null}
          </section>

          <aside className="space-y-4">
            <div className="card p-5">
              <h3 className="flex items-center gap-2 text-xs font-semibold">
                <Users className="h-3.5 w-3.5 text-primary" />
                一次只服务一个人
              </h3>
              <ul className="mt-3 space-y-2 text-[11px] leading-5 text-muted">
                <li>· 服务器只有 2 核 1.9GB，并发蒸馏会拖慢所有人，所以按顺序轮流。</li>
                <li>· 轮到你时独占一个工作位，默认 {state.data?.visit_minutes ?? 30} 分钟。</li>
                <li>· 结束后座位自动释放，下一位自动进入。</li>
              </ul>
            </div>

            <div className="card p-5">
              <h3 className="flex items-center gap-2 text-xs font-semibold">
                <ShieldCheck className="h-3.5 w-3.5 text-primary" />
                关于你的 Key 与资料
              </h3>
              <ul className="mt-3 space-y-2 text-[11px] leading-5 text-muted">
                <li>· Key 只在本次体验内有效，加密后短暂保存在服务器。</li>
                <li>· 体验结束、超时或服务重启时，Key 与上传资料一起删除。</li>
                <li>· 明文 Key 不会回传到浏览器，也不会写进日志。</li>
                <li>· 你上传的资料只用于你的这次蒸馏，不会进入他人工作区。</li>
              </ul>
            </div>

            <div className="card p-5">
              <h3 className="flex items-center gap-2 text-xs font-semibold">
                <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
                进来后先做什么
              </h3>
              <ol className="mt-3 space-y-2 text-[11px] leading-5 text-muted">
                <li>1. 已经有一个示例项目，直接点「开始蒸馏」。</li>
                <li>2. 看断言与证据如何一一对应。</li>
                <li>3. 批准后编译，导出人物包。</li>
              </ol>
              <a
                href="https://github.com/suringyun2025/belike-someone"
                target="_blank"
                rel="noreferrer"
                className="mt-3 flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
              >
                了解项目与本地部署
                <ArrowRight className="h-3 w-3" />
              </a>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

function SeatBadge({
  state,
  occupant,
  waiting,
}: {
  state?: string;
  occupant?: { nickname?: string; seconds_left?: number } | null;
  waiting: number;
}) {
  if (state === "busy") {
    return (
      <div className="flex items-center gap-2 rounded-full border border-warning/30 bg-warning/10 px-3 py-1.5 text-[11px] text-warning">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warning" />
        {occupant?.nickname || "有人"} 正在使用
        {occupant?.seconds_left ? ` · 剩余 ${Math.ceil(occupant.seconds_left / 60)} 分钟` : ""}
        {waiting > 0 ? ` · 排队 ${waiting} 人` : ""}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 rounded-full border border-success/30 bg-success/10 px-3 py-1.5 text-[11px] text-success">
      <span className="h-1.5 w-1.5 rounded-full bg-success" />
      空闲中 · 可直接进入
    </div>
  );
}

function formatWait(seconds: number): string {
  if (!seconds || seconds <= 0) return "不到 1 分钟";
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  return `${hours} 小时 ${minutes % 60} 分钟`;
}