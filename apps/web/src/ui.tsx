import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  Info,
  Loader2,
  Search,
  X,
} from "lucide-react";
import clsx, { type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

export function Button({
  className,
  variant = "secondary",
  size = "md",
  loading = false,
  children,
  type = "button",
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}) {
  return (
    <button
      type={type}
      className={cn(
        "btn",
        variant === "primary" && "btn-primary",
        variant === "secondary" && "btn-secondary",
        variant === "ghost" && "btn-ghost",
        variant === "danger" && "btn-danger",
        size === "sm" && "btn-sm",
        size === "lg" && "btn-lg",
        className,
      )}
      disabled={loading || disabled}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      {children}
    </button>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">{eyebrow}</p>
        ) : null}
        <h1 className="text-balance text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Card({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("card", className)} {...props}>
      {children}
    </div>
  );
}

export function CardHeader({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("flex items-start justify-between gap-4 p-5", className)}>{children}</div>;
}

export function CardTitle({ className, children }: { className?: string; children: ReactNode }) {
  return <h3 className={cn("text-sm font-semibold tracking-tight text-text", className)}>{children}</h3>;
}

export function CardDescription({ className, children }: { className?: string; children: ReactNode }) {
  return <p className={cn("mt-1 text-xs leading-5 text-muted", className)}>{children}</p>;
}

export function CardContent({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("px-5 pb-5", className)}>{children}</div>;
}

type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger" | "info" | "accent";

const badgeTones: Record<BadgeTone, string> = {
  neutral: "border-border bg-elevated text-muted",
  primary: "border-primary/20 bg-primary/10 text-primary",
  success: "border-success/20 bg-success/10 text-success",
  warning: "border-warning/25 bg-warning/10 text-warning",
  danger: "border-danger/20 bg-danger/10 text-danger",
  info: "border-info/20 bg-info/10 text-info",
  accent: "border-accent/25 bg-accent/10 text-accent",
};

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: BadgeTone;
  className?: string;
  children: ReactNode;
}) {
  return <span className={cn("badge", badgeTones[tone], className)}>{children}</span>;
}

const statusMap: Record<string, { label: string; tone: BadgeTone }> = {
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "运行中", tone: "info" },
  waiting_for_review: { label: "待审核", tone: "warning" },
  paused: { label: "已暂停", tone: "neutral" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "neutral" },
  uploaded: { label: "待解析", tone: "neutral" },
  parsed: { label: "已解析", tone: "success" },
  needs_ocr: { label: "需 OCR", tone: "warning" },
  needs_asr: { label: "需 ASR", tone: "warning" },
  excluded: { label: "已排除", tone: "neutral" },
  proposed: { label: "待审核", tone: "warning" },
  approved: { label: "已批准", tone: "success" },
  rejected: { label: "已驳回", tone: "danger" },
  compiled: { label: "已编译", tone: "info" },
  validated: { label: "已校验", tone: "success" },
  exported: { label: "已导出", tone: "success" },
  draft: { label: "草稿", tone: "neutral" },
  open: { label: "待处理", tone: "warning" },
  resolved: { label: "已解决", tone: "success" },
  ignored: { label: "已忽略", tone: "neutral" },
  ok: { label: "连接正常", tone: "success" },
  error: { label: "连接失败", tone: "danger" },
  untested: { label: "未测试", tone: "neutral" },
  succeeded: { label: "成功", tone: "success" },
  pending: { label: "等待", tone: "neutral" },
  skipped: { label: "跳过", tone: "neutral" },
  recorded: { label: "已记录", tone: "info" },
  structural: { label: "结构检查", tone: "info" },
  not_run: { label: "未运行", tone: "neutral" },
};

export function StatusBadge({ status }: { status: string }) {
  const info = statusMap[status] || { label: status || "未知", tone: "neutral" as BadgeTone };
  return <Badge tone={info.tone}>{info.label}</Badge>;
}

const dimensionMap: Record<string, { label: string; tone: BadgeTone }> = {
  professional: { label: "专业能力", tone: "primary" },
  decision: { label: "思维决策", tone: "accent" },
  workflow: { label: "工作流", tone: "info" },
  style: { label: "表达风格", tone: "warning" },
  boundary: { label: "边界", tone: "danger" },
  knowledge: { label: "知识", tone: "success" },
};

export function DimensionBadge({ dimension }: { dimension: string }) {
  const info = dimensionMap[dimension] || { label: dimension, tone: "neutral" as BadgeTone };
  return <Badge tone={info.tone}>{info.label}</Badge>;
}

export const dimensionLabels = Object.fromEntries(
  Object.entries(dimensionMap).map(([key, value]) => [key, value.label]),
);

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("input", className)} {...props} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn("textarea", className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select className={cn("select pr-9", className)} {...props}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
    </div>
  );
}

export function Field({
  label,
  hint,
  required,
  children,
  className,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("block", className)}>
      <span className="label">
        {label} {required ? <span className="text-danger">*</span> : null}
      </span>
      {children}
      {hint ? <span className="mt-1.5 block text-[11px] leading-5 text-muted">{hint}</span> : null}
    </label>
  );
}

export function Progress({
  value,
  tone = "primary",
  className,
}: {
  value: number;
  tone?: "primary" | "success" | "warning" | "danger";
  className?: string;
}) {
  const colors = {
    primary: "bg-primary",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
  };
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-border/70", className)}>
      <div
        className={cn("h-full rounded-full transition-all duration-500", colors[tone])}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

export function Tabs({
  items,
  value,
  onChange,
  className,
}: {
  items: Array<{ value: string; label: string; count?: number }>;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("tab-scroll flex items-center gap-1 overflow-x-auto border-b border-border", className)}>
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onChange(item.value)}
          className={cn(
            "relative flex shrink-0 items-center gap-2 px-3.5 py-2.5 text-sm font-medium text-muted transition-colors hover:text-text",
            value === item.value && "text-primary",
          )}
        >
          {item.label}
          {typeof item.count === "number" ? (
            <span className="rounded-full bg-elevated px-1.5 text-[10px] text-muted">{item.count}</span>
          ) : null}
          {value === item.value ? (
            <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary" />
          ) : null}
        </button>
      ))}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;
  const widths = { sm: "max-w-md", md: "max-w-2xl", lg: "max-w-4xl", xl: "max-w-6xl" };
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/45 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "animate-rise relative flex max-h-[90vh] w-full flex-col overflow-hidden rounded-2xl border bg-surface shadow-2xl",
          widths[size],
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
          <div>
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
            {description ? <p className="mt-1 text-xs leading-5 text-muted">{description}</p> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted transition hover:bg-elevated hover:text-text"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">{children}</div>
        {footer ? <div className="flex items-center justify-end gap-2 border-t px-5 py-3">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-14 text-center", className)}>
      {icon ? (
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border bg-elevated text-muted">
          {icon}
        </div>
      ) : null}
      <h3 className="text-sm font-semibold">{title}</h3>
      {description ? <p className="mt-1.5 max-w-md text-xs leading-6 text-muted">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-5 w-5 animate-spin text-muted", className)} />;
}

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "primary",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  tone?: "primary" | "success" | "warning" | "danger" | "info";
}) {
  const tones = {
    primary: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    danger: "bg-danger/10 text-danger",
    info: "bg-info/10 text-info",
  };
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted">{label}</p>
          <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
          {hint ? <p className="mt-1 text-[11px] text-muted">{hint}</p> : null}
        </div>
        {icon ? <div className={cn("rounded-xl p-2", tones[tone])}>{icon}</div> : null}
      </div>
    </Card>
  );
}

export function Alert({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "info" | "warning" | "danger" | "success";
  title?: string;
  children?: ReactNode;
  className?: string;
}) {
  const tones = {
    info: "border-info/20 bg-info/5 text-info",
    warning: "border-warning/25 bg-warning/5 text-warning",
    danger: "border-danger/20 bg-danger/5 text-danger",
    success: "border-success/20 bg-success/5 text-success",
  };
  const icons = {
    info: <Info className="h-4 w-4" />,
    warning: <AlertTriangle className="h-4 w-4" />,
    danger: <AlertTriangle className="h-4 w-4" />,
    success: <CheckCircle2 className="h-4 w-4" />,
  };
  return (
    <div className={cn("rounded-xl border px-3.5 py-3 text-xs leading-6", tones[tone], className)}>
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0">{icons[tone]}</span>
        <div>
          {title ? <p className="font-semibold">{title}</p> : null}
          {children ? <div className="opacity-90">{children}</div> : null}
        </div>
      </div>
    </div>
  );
}

export function CopyButton({ value, label = "复制" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      title={label}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? "已复制" : label}
    </Button>
  );
}

export function CodeBlock({ code, className }: { code: string; className?: string }) {
  return (
    <div className={cn("group relative rounded-xl border bg-elevated", className)}>
      <pre className="max-h-[520px] overflow-auto p-4 pr-20 font-mono text-xs leading-6 text-text">
        {code}
      </pre>
      <div className="absolute right-2 top-2">
        <CopyButton value={code} />
      </div>
    </div>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder = "搜索…",
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
      <input
        className="input pl-9"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

type ToastVariant = "success" | "error" | "info";
interface ToastItem {
  id: number;
  title: string;
  description?: string;
  variant: ToastVariant;
}

const ToastContext = createContext<{
  toast: (item: Omit<ToastItem, "id">) => void;
} | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const toast = useCallback((item: Omit<ToastItem, "id">) => {
    const id = Date.now() + Math.random();
    setItems((current) => [...current, { ...item, id }]);
    window.setTimeout(() => {
      setItems((current) => current.filter((entry) => entry.id !== id));
    }, 4200);
  }, []);
  const value = useMemo(() => ({ toast }), [toast]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className={cn(
              "animate-rise pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-surface p-3.5 shadow-xl",
              item.variant === "success" && "border-success/30",
              item.variant === "error" && "border-danger/30",
              item.variant === "info" && "border-info/30",
            )}
          >
            <span
              className={cn(
                "mt-0.5",
                item.variant === "success" && "text-success",
                item.variant === "error" && "text-danger",
                item.variant === "info" && "text-info",
              )}
            >
              {item.variant === "success" ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : item.variant === "error" ? (
                <AlertTriangle className="h-4 w-4" />
              ) : (
                <Info className="h-4 w-4" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold">{item.title}</p>
              {item.description ? (
                <p className="mt-0.5 break-words text-[11px] leading-5 text-muted">{item.description}</p>
              ) : null}
            </div>
            <button
              type="button"
              className="rounded p-0.5 text-muted hover:bg-elevated"
              onClick={() => setItems((current) => current.filter((entry) => entry.id !== item.id))}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast 必须在 ToastProvider 内使用");
  return context.toast;
}
