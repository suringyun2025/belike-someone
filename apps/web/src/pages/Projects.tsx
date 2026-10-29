import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Boxes,
  ClipboardCheck,
  Database,
  FolderKanban,
  Plus,
  Search,
  Sparkles,
} from "lucide-react";
import { api } from "../api";
import type { Project } from "../types";
import {
  Badge,
  Button,
  Card,
  CardContent,
  EmptyState,
  Field,
  Input,
  Modal,
  PageHeader,
  Spinner,
  StatusBadge,
  Textarea,
  useToast,
} from "../ui";
import { relativeTime, truncate } from "../lib/format";

const emptyForm = {
  name: "",
  codename: "",
  purpose: "",
  authorization_note: "",
  prohibited_uses: "",
  target_platforms: "Claude Code, Cursor, Qoder",
};

export function ProjectsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState(params.get("new") === "1");
  const [form, setForm] = useState(emptyForm);
  const [search, setSearch] = useState("");
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });

  useEffect(() => {
    if (params.get("new") === "1") setOpen(true);
  }, [params]);

  const create = useMutation({
    mutationFn: () =>
      api.createProject({
        ...form,
        target_platforms: form.target_platforms
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      toast({ title: "项目已创建", description: "接下来导入资料并运行蒸馏。", variant: "success" });
      setOpen(false);
      setForm(emptyForm);
      navigate(`/projects/${project.id}`);
    },
    onError: (error: Error) => toast({ title: "创建失败", description: error.message, variant: "error" }),
  });

  const demo = useMutation({
    mutationFn: api.createDemo,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      navigate(`/projects/${result.project_id}`);
    },
    onError: (error: Error) => toast({ title: "创建失败", description: error.message, variant: "error" }),
  });

  const filtered = useMemo(() => {
    const items = projects.data || [];
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((project) =>
      [project.name, project.codename, project.purpose].some((value) =>
        value?.toLowerCase().includes(query),
      ),
    );
  }, [projects.data, search]);

  return (
    <div className="mx-auto max-w-[1400px] animate-in">
      <PageHeader
        eyebrow="人物项目"
        title="管理每一个蒸馏目标"
        description="每个项目对应一个人物或角色。资料、断言、模型配置、Skills 与导出版本都归属于项目。"
        actions={
          <>
            <Button variant="secondary" loading={demo.isPending} onClick={() => demo.mutate()}>
              <Sparkles className="h-4 w-4" />
              示例项目
            </Button>
            <Button variant="primary" onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" />
              新建项目
            </Button>
          </>
        }
      />

      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="relative w-80">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input
            className="pl-9"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索项目名称、代号或用途…"
          />
        </div>
        <p className="text-xs text-muted">{filtered.length} 个项目</p>
      </div>

      {projects.isLoading ? (
        <div className="flex h-60 items-center justify-center"><Spinner /></div>
      ) : filtered.length === 0 ? (
        <Card>
          <EmptyState
            icon={<FolderKanban className="h-5 w-5" />}
            title={search ? "没有匹配的项目" : "从第一个项目开始"}
            description={
              search
                ? "换个关键词试试。"
                : "创建一个示例项目，或新建空白项目并上传访谈、文档、聊天记录或代码。"
            }
            action={
              !search ? (
                <div className="flex gap-2">
                  <Button variant="secondary" loading={demo.isPending} onClick={() => demo.mutate()}>
                    <Sparkles className="h-4 w-4" />
                    创建示例项目
                  </Button>
                  <Button variant="primary" onClick={() => setOpen(true)}>
                    <Plus className="h-4 w-4" />
                    新建项目
                  </Button>
                </div>
              ) : null
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {filtered.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}

      <Modal
        open={open}
        onClose={() => {
          setOpen(false);
          if (params.get("new")) {
            params.delete("new");
            setParams(params, { replace: true });
          }
        }}
        title="新建人物项目"
        description="先定义用途与授权范围，再导入资料。所有蒸馏结果都会记录来源和审核状态。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
            <Button
              variant="primary"
              loading={create.isPending}
              disabled={!form.name.trim()}
              onClick={() => create.mutate()}
            >
              创建项目
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="项目名称" required>
              <Input
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="例如：资深后端架构师"
              />
            </Field>
            <Field label="人物代号" hint="用于 Skill 与导出包，不要填真实姓名">
              <Input
                value={form.codename}
                onChange={(event) => setForm({ ...form, codename: event.target.value })}
                placeholder="例如：架构师 A"
              />
            </Field>
          </div>
          <Field label="项目用途">
            <Textarea
              value={form.purpose}
              onChange={(event) => setForm({ ...form, purpose: event.target.value })}
              placeholder="说明蒸馏结果将用于什么场景"
            />
          </Field>
          <Field label="授权/来源备注" hint="记录资料授权、来源与使用边界；不要粘贴敏感信息">
            <Textarea
              value={form.authorization_note}
              onChange={(event) => setForm({ ...form, authorization_note: event.target.value })}
              placeholder="例如：本人授权的工作笔记与公开文章，仅用于内部知识助手"
            />
          </Field>
          <Field label="禁止用途">
            <Textarea
              value={form.prohibited_uses}
              onChange={(event) => setForm({ ...form, prohibited_uses: event.target.value })}
              placeholder="例如：不得用于冒充本人、对外发布或高风险决策"
            />
          </Field>
          <Field label="目标平台" hint="用逗号分隔">
            <Input
              value={form.target_platforms}
              onChange={(event) => setForm({ ...form, target_platforms: event.target.value })}
              placeholder="Claude Code, Cursor, Qoder"
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  return (
    <Link to={`/projects/${project.id}`} className="card card-hover group block p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-accent/10 text-primary">
            <FolderKanban className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-sm font-semibold">{project.name}</h3>
              <Badge tone={project.status === "active" ? "success" : "neutral"}>
                {project.status === "active" ? "进行中" : "已归档"}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-muted">{project.codename || "未设置代号"} · 更新于 {relativeTime(project.updated_at)}</p>
          </div>
        </div>
        <ArrowRight className="h-4 w-4 shrink-0 text-muted/50 transition group-hover:translate-x-0.5 group-hover:text-primary" />
      </div>
      <p className="mt-4 line-clamp-2 min-h-10 text-xs leading-5 text-muted">
        {truncate(project.purpose, 120) || "尚未填写项目用途。"}
      </p>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <Metric icon={<Database className="h-3.5 w-3.5" />} label="资料" value={project.source_count} />
        <Metric icon={<ClipboardCheck className="h-3.5 w-3.5" />} label="已批准" value={`${project.approved_count}/${project.claim_count}`} />
        <Metric icon={<Boxes className="h-3.5 w-3.5" />} label="Skills" value={project.skill_count} />
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {(project.target_platforms || []).slice(0, 4).map((platform) => (
          <Badge key={platform} tone="neutral">{platform}</Badge>
        ))}
        {project.target_platforms?.length > 4 ? <Badge tone="neutral">+{project.target_platforms.length - 4}</Badge> : null}
      </div>
    </Link>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-elevated/50 px-2.5 py-2">
      <div className="flex items-center gap-1.5 text-[10px] text-muted">
        {icon}
        {label}
      </div>
      <p className="mt-1 text-sm font-semibold">{value}</p>
    </div>
  );
}
