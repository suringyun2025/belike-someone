import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  Boxes,
  ChevronRight,
  Clock,
  FolderKanban,
  LayoutDashboard,
  Menu,
  Moon,
  Server,
  Settings as SettingsIcon,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { cn } from "./ui";
import { useTheme } from "./lib/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { AuthUser } from "./types";
import { LogOut } from "lucide-react";

const navigation = [
  { to: "/", label: "仪表盘", icon: LayoutDashboard, end: true },
  { to: "/projects", label: "人物项目", icon: FolderKanban },
  { to: "/providers", label: "模型与 API", icon: Server },
  { to: "/ops", label: "运行状态", icon: Activity },
  { to: "/settings", label: "设置", icon: SettingsIcon },
];

function breadcrumb(pathname: string) {
  if (pathname.startsWith("/projects/")) return ["人物项目", "项目工作台"];
  if (pathname.startsWith("/projects")) return ["工作台", "人物项目"];
  if (pathname.startsWith("/providers")) return ["工作台", "模型与 API"];
  if (pathname.startsWith("/ops")) return ["工作台", "运行状态"];
  if (pathname.startsWith("/settings")) return ["工作台", "设置"];
  return ["工作台", "仪表盘"];
}

export function Layout() {
  const location = useLocation();
  const { dark, toggle } = useTheme();
  const queryClient = useQueryClient();
  // The account block only makes sense when there is a real login. The server
  // tells us which mode it is in; single-user builds hide the block entirely.
  const authConfig = useQuery({
    queryKey: ["auth-config"],
    queryFn: api.authConfig,
    staleTime: 60_000,
    retry: false,
  });
  const isMultiuser = Boolean(authConfig.data?.multiuser);
  const isSandbox = Boolean(authConfig.data?.sandbox);
  const me = useQuery<AuthUser>({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    staleTime: 60_000,
    enabled: isMultiuser,
  });
  const account = isMultiuser ? me.data : undefined;
  const crumbs = breadcrumb(location.pathname);
  // 窄屏时侧边栏改为抽屉；桌面保持常驻，避免多一次点击。
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 路由变化时自动收起抽屉，否则点击导航后会把内容挡住。
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const sidebar = (
    <>
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-fg shadow-sm">
          <Boxes className="h-5 w-5" />
          <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold tracking-tight">蒸馏平台</p>
          <p className="truncate text-[10px] uppercase tracking-[0.16em] text-muted">
            Persona Distillation
          </p>
        </div>
        <button
          type="button"
          onClick={() => setDrawerOpen(false)}
          className="rounded-lg p-1.5 text-muted transition hover:bg-elevated lg:hidden"
          aria-label="关闭导航"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        <p className="px-3 pb-1.5 pt-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted/70">
          工作台
        </p>
        {navigation.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => cn("nav-link", isActive && "nav-link-active")}
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        ))}

        <div className="mx-3 my-4 border-t border-border" />
        <div className="rounded-xl border border-dashed border-border bg-elevated/50 p-3">
          <div className="flex items-center gap-2 text-xs font-medium">
            <Sparkles className="h-3.5 w-3.5 text-accent" />
            证据优先
          </div>
          <p className="mt-1.5 text-[11px] leading-5 text-muted">
            所有能力都从资料片段出发，经人工审核后才进入 Skill。
          </p>
        </div>
      </nav>

      <div className="border-t border-border px-3 py-3">
        {isSandbox ? <SandboxPanel /> : null}
        {account && !isSandbox ? (
          <div className="mb-2 rounded-xl border bg-elevated/60 px-3 py-2">
            <p className="truncate text-[11px] font-medium" title={account.email}>
              {account.display_name || account.email}
            </p>
            <p className="truncate text-[10px] text-muted">
              {account.project_count}/{account.max_projects} 个项目
            </p>
            <button
              type="button"
              className="mt-1.5 flex items-center gap-1 text-[10px] text-muted transition hover:text-danger"
              onClick={async () => {
                await api.logout().catch(() => undefined);
                queryClient.clear();
                window.location.reload();
              }}
            >
              <LogOut className="h-3 w-3" />
              退出登录
            </button>
          </div>
        ) : null}
        <button type="button" onClick={toggle} className="nav-link w-full justify-between">
          <span className="flex items-center gap-3">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {dark ? "切换浅色" : "切换深色"}
          </span>
          <span
            className={cn(
              "h-5 w-9 rounded-full p-0.5 transition-colors",
              dark ? "bg-primary" : "bg-border",
            )}
          >
            <span
              className={cn(
                "block h-4 w-4 rounded-full bg-surface shadow-sm transition-transform",
                dark && "translate-x-4",
              )}
            />
          </span>
        </button>
        <div className="mt-2 flex items-center justify-between px-3 text-[10px] text-muted">
          <span>本地优先 · v0.2</span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            Agent Skills
          </span>
        </div>
      </div>
    </>
  );

  return (
    <div className="flex min-h-screen bg-bg">
      {/* 桌面侧边栏 */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-border bg-surface lg:flex">
        {sidebar}
      </aside>

      {/* 窄屏抽屉 */}
      {drawerOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/45 backdrop-blur-[2px]"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <aside className="relative flex h-full w-64 flex-col border-r border-border bg-surface">
            {sidebar}
          </aside>
        </div>
      ) : null}

      <div className="flex min-h-screen min-w-0 flex-1 flex-col lg:ml-60">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-border/80 bg-bg/85 px-4 backdrop-blur sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="rounded-lg p-1.5 text-muted transition hover:bg-elevated hover:text-text lg:hidden"
              aria-label="打开导航"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
              {crumbs.map((crumb, index) => (
                <span key={crumb} className="flex min-w-0 items-center gap-1.5">
                  {index > 0 ? <ChevronRight className="h-3 w-3 shrink-0 text-muted/50" /> : null}
                  <span
                    className={cn(
                      "truncate",
                      index === crumbs.length - 1 ? "font-medium text-text" : "",
                    )}
                  >
                    {crumb}
                  </span>
                </span>
              ))}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="badge border-success/20 bg-success/10 text-success">
              <span className="h-1.5 w-1.5 rounded-full bg-success" />
              <span className="hidden sm:inline">本地优先</span>
            </span>
            <span className="badge hidden border-border bg-surface text-muted sm:inline-flex">
              127.0.0.1
            </span>
          </div>
        </header>
        <main className="min-w-0 flex-1 px-4 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
/**
 * Sidebar block for a demo visit: a live countdown and a one-click exit.
 *
 * The countdown matters because the seat is time-boxed and someone is waiting
 * behind it; a visitor who cannot see the clock either wastes their own turn or
 * gets cut off mid-review. The exit button is deliberately explicit about
 * deleting data, since that is what it does.
 */
function SandboxPanel() {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);

  const me = useQuery({
    queryKey: ["sandbox-me"],
    queryFn: api.sandboxMe,
    staleTime: 30_000,
    retry: 0,
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (me.data?.visit?.seconds_left != null) {
      setSecondsLeft(me.data.visit.seconds_left);
    }
  }, [me.data]);

  // Tick locally between polls; the server value is the authority and resets it.
  useEffect(() => {
    if (secondsLeft == null) return;
    const timer = window.setInterval(() => {
      setSecondsLeft((value) => (value == null ? null : Math.max(0, value - 1)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [secondsLeft == null]);

  if (!me.data?.sandbox || !me.data.visit) return null;

  const minutes = secondsLeft == null ? null : Math.floor(secondsLeft / 60);
  const seconds = secondsLeft == null ? 0 : secondsLeft % 60;
  const urgent = secondsLeft != null && secondsLeft <= 300;

  return (
    <div className="mb-2 rounded-xl border bg-elevated/60 px-3 py-2">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-[10px] font-medium text-muted">
          <Clock className="h-3 w-3" />
          体验剩余
        </span>
        <span
          className={cn(
            "font-mono text-xs font-medium tabular-nums",
            urgent ? "text-danger" : "text-fg",
          )}
        >
          {minutes == null ? "--:--" : `${minutes}:${String(seconds).padStart(2, "0")}`}
        </span>
      </div>
      <p className="mt-1 truncate text-[10px] text-muted" title={me.data.visit.model_id}>
        {me.data.visit.nickname || "访客"} · {me.data.visit.model_id}
      </p>

      {confirming ? (
        <div className="mt-2 rounded-lg border border-danger/30 bg-danger/5 p-2">
          <p className="text-[10px] leading-4 text-danger">
            结束会立即删除本次所有资料与 Key，无法恢复。确定？
          </p>
          <div className="mt-1.5 flex gap-2">
            <button
              type="button"
              className="flex-1 rounded-md bg-danger px-2 py-1 text-[10px] font-medium text-white"
              onClick={async () => {
                await api.sandboxExit().catch(() => undefined);
                queryClient.clear();
                window.location.href = "/";
              }}
            >
              结束并删除
            </button>
            <button
              type="button"
              className="flex-1 rounded-md border px-2 py-1 text-[10px]"
              onClick={() => setConfirming(false)}
            >
              取消
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="mt-1.5 flex items-center gap-1 text-[10px] text-muted transition hover:text-danger"
          onClick={() => setConfirming(true)}
        >
          <LogOut className="h-3 w-3" />
          结束体验，让给下一位
        </button>
      )}
    </div>
  );
}
