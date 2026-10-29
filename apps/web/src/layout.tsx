import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  Boxes,
  ChevronRight,
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