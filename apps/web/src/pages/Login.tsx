import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Boxes,
  CheckCircle2,
  Loader2,
  Lock,
  Mail,
  ShieldCheck,
  UserPlus,
} from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "../api";

type Mode = "login" | "register";

export function LoginPage() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");

  const config = useQuery({ queryKey: ["auth-config"], queryFn: api.authConfig });
  const allowRegister = config.data?.allow_registration ?? false;

  const submit = useMutation({
    mutationFn: () =>
      mode === "login"
        ? api.login({ email, password })
        : api.register({ email, password, display_name: displayName }),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
      queryClient.invalidateQueries();
    },
    onError: (err: Error) => {
      // Surface request ids so a user can quote them when reporting a problem.
      if (err instanceof ApiError) {
        setError(err.requestId ? `${err.message}（请求 ${err.requestId}）` : err.message);
      } else {
        setError(err.message);
      }
    },
  });

  const canSubmit = email.trim().length > 2 && password.length > 0 && !submit.isPending;

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <div className="relative flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-fg shadow-sm">
            <Boxes className="h-6 w-6" />
            <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" />
          </div>
          <div>
            <p className="text-base font-semibold tracking-tight">蒸馏平台</p>
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted">
              Persona Distillation
            </p>
          </div>
        </div>

        <div className="card p-6">
          <div className="mb-5">
            <h1 className="text-lg font-semibold tracking-tight">
              {mode === "login" ? "登录" : "创建账号"}
            </h1>
            <p className="mt-1 text-xs leading-5 text-muted">
              {mode === "login"
                ? "每个账号的资料、断言、模型密钥与导出包相互隔离。"
                : "注册后你会获得独立的工作区；他人无法访问你的资料与密钥。"}
            </p>
          </div>

          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              setError("");
              submit.mutate();
            }}
          >
            <label className="block">
              <span className="label">邮箱</span>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  className="input pl-9"
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  required
                />
              </div>
            </label>

            {mode === "register" ? (
              <label className="block">
                <span className="label">显示名称（可选）</span>
                <input
                  className="input"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="怎么称呼你"
                  maxLength={120}
                />
              </label>
            ) : null}

            <label className="block">
              <span className="label">密码</span>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  className="input pl-9"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={mode === "register" ? "至少 10 个字符" : "输入密码"}
                  required
                />
              </div>
            </label>

            {error ? (
              <div className="flex items-start gap-2 rounded-xl border border-danger/25 bg-danger/5 px-3 py-2.5 text-xs leading-5 text-danger">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span className="break-all">{error}</span>
              </div>
            ) : null}

            <button
              type="submit"
              disabled={!canSubmit}
              className="btn btn-primary btn-lg w-full"
            >
              {submit.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : mode === "login" ? (
                <Lock className="h-4 w-4" />
              ) : (
                <UserPlus className="h-4 w-4" />
              )}
              {mode === "login" ? "登录" : "创建账号"}
            </button>
          </form>

          {allowRegister ? (
            <div className="mt-4 border-t pt-4 text-center text-xs text-muted">
              {mode === "login" ? "还没有账号？" : "已有账号？"}
              <button
                type="button"
                className="ml-1 font-medium text-primary hover:underline"
                onClick={() => {
                  setMode(mode === "login" ? "register" : "login");
                  setError("");
                }}
              >
                {mode === "login" ? "注册" : "去登录"}
              </button>
            </div>
          ) : (
            <p className="mt-4 border-t pt-4 text-center text-[11px] leading-5 text-muted">
              本实例未开放自助注册，请联系管理员开通账号。
            </p>
          )}
        </div>

        <div className="mt-5 space-y-2">
          <SecurityNote
            icon={<ShieldCheck className="h-3.5 w-3.5" />}
            text="密码使用 Argon2id 哈希存储；会话令牌仅保存摘要，数据库泄露也无法直接复用。"
          />
          <SecurityNote
            icon={<CheckCircle2 className="h-3.5 w-3.5" />}
            text="模型 API Key 由你的账号独立加密，其他用户与管理员都无法读取明文。"
          />
        </div>
      </div>
    </div>
  );
}

function SecurityNote({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-start gap-2 px-1 text-[11px] leading-5 text-muted">
      <span className="mt-0.5 shrink-0 text-primary/70">{icon}</span>
      <span>{text}</span>
    </div>
  );
}