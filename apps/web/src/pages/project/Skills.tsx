import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  ClipboardCheck,
  Code2,
  FlaskConical,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api } from "../../api";
import type { Skill } from "../../types";
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
  CodeBlock,
  DimensionBadge,
  EmptyState,
  Modal,
  Spinner,
  StatusBadge,
  Tabs,
  useToast,
} from "../../ui";
import { truncate, formatDate } from "../../lib/format";

export function SkillsTab({ project, providers, setTab }: ProjectTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [selected, setSelected] = useState<Skill | null>(null);
  const skills = useQuery({ queryKey: ["skills", project.id], queryFn: () => api.skills(project.id) });
  const providerId = project.provider_id || providers[0]?.id || null;

  const validate = useMutation({
    mutationFn: (skillId: string) => api.validateSkill(skillId),
    onSuccess: (report) => {
      queryClient.invalidateQueries({ queryKey: ["skills", project.id] });
      toast({
        title: report.ok ? "静态校验通过" : "静态校验失败",
        description: report.errors[0] || (report.warnings[0] ?? ""),
        variant: report.ok ? "success" : "error",
      });
    },
    onError: (error: Error) => toast({ title: "校验失败", description: error.message, variant: "error" }),
  });

  const evaluate = useMutation({
    mutationFn: (skillId: string) => {
      if (!providerId) throw new Error("请先在“模型与 API”配置 Provider");
      return api.evaluateSkill(skillId, {
        provider_id: providerId,
        judge_provider_id: providerId,
        max_cases: 10,
      });
    },
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["eval-runs", project.id] });
      queryClient.invalidateQueries({ queryKey: ["eval-cases", project.id] });
      toast({ title: "LLM-as-judge 已完成", description: run.report, variant: "success" });
    },
    onError: (error: Error) => toast({ title: "评测失败", description: error.message, variant: "error" }),
  });

  useEffect(() => {
    if (selected) {
      const latest = skills.data?.find((skill) => skill.id === selected.id);
      if (latest && latest !== selected) setSelected(latest);
    }
  }, [skills.data, selected]);

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Skills 工作台</CardTitle>
            <CardDescription>
              每个 Skill 由已批准断言编译而来。SKILL.md 保持精简，证据与评测用例放在 references/ 与 evals/。
            </CardDescription>
          </div>
          <Button variant="secondary" onClick={() => setTab("pipeline")}>
            <FlaskConical className="h-4 w-4" />
            编译 / 重新编译
          </Button>
        </CardHeader>
      </Card>

      {skills.isLoading ? (
        <div className="flex h-48 items-center justify-center"><Spinner /></div>
      ) : !skills.data?.length ? (
        <Card>
          <EmptyState
            icon={<Boxes className="h-5 w-5" />}
            title="还没有 Skills"
            description="先在审核收件箱批准断言，然后运行编译任务。编译会自动执行静态校验并生成评测用例。"
            action={<Button variant="primary" onClick={() => setTab("review")}>去审核断言 <ArrowRight className="h-3.5 w-3.5" /></Button>}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {skills.data.map((skill) => (
            <button
              key={skill.id}
              type="button"
              onClick={() => setSelected(skill)}
              className="card card-hover p-5 text-left"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <Boxes className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold">{skill.title}</h3>
                      <DimensionBadge dimension={skill.dimension} />
                    </div>
                    <p className="mt-0.5 font-mono text-[10px] text-muted">{skill.name} · v{skill.version}</p>
                  </div>
                </div>
                <StatusBadge status={skill.status} />
              </div>
              <p className="mt-3 line-clamp-2 min-h-10 text-xs leading-5 text-muted">{truncate(skill.description, 150)}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-muted">
                <Badge tone="neutral">{skill.claim_ids.length} 条断言</Badge>
                <Badge tone="neutral">{Object.keys(skill.files || {}).length} 个文件</Badge>
                {skill.validation?.static?.ok ? <Badge tone="success">静态校验通过</Badge> : null}
              </div>
            </button>
          ))}
        </div>
      )}

      <SkillModal
        skill={selected}
        onClose={() => setSelected(null)}
        onValidate={(id) => validate.mutate(id)}
        onEvaluate={(id) => evaluate.mutate(id)}
        validating={validate.isPending}
        evaluating={evaluate.isPending}
      />
    </div>
  );
}

function SkillModal({
  skill,
  onClose,
  onValidate,
  onEvaluate,
  validating,
  evaluating,
}: {
  skill: Skill | null;
  onClose: () => void;
  onValidate: (id: string) => void;
  onEvaluate: (id: string) => void;
  validating: boolean;
  evaluating: boolean;
}) {
  const [tab, setTab] = useState("skill");
  useEffect(() => setTab("skill"), [skill?.id]);
  const versions = useQuery({
    queryKey: ["skill-versions", skill?.id],
    queryFn: () => api.skillVersions(skill!.id),
    enabled: Boolean(skill?.id),
  });
  const versionList = versions.data || [];
  const [diffPair, setDiffPair] = useState<{ from: number; to: number } | null>(null);
  const diff = useQuery({
    queryKey: ["skill-diff", skill?.id, diffPair?.from, diffPair?.to],
    queryFn: () => api.skillDiff(skill!.id, diffPair!.from, diffPair!.to),
    enabled: Boolean(skill?.id && diffPair),
  });
  useEffect(() => setDiffPair(null), [skill?.id]);
  if (!skill) return null;
  const files = skill.files || {};
  const content =
    tab === "skill"
      ? files["SKILL.md"] || skill.content
      : tab === "evidence"
        ? files["references/evidence.md"] || "（没有证据文件）"
        : tab === "evals"
          ? files["evals/evals.json"] || "（没有评测用例）"
          : diff.data?.diff || "（选择两个版本以比较）";
  const staticReport = skill.validation?.static;
  const evalInfo = skill.validation?.eval;

  return (
    <Modal
      open={Boolean(skill)}
      onClose={onClose}
      title={`${skill.title} · ${skill.name}`}
      description={skill.description}
      size="xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>关闭</Button>
          <Button variant="secondary" loading={validating} onClick={() => onValidate(skill.id)}>
            <ShieldCheck className="h-4 w-4" />
            静态校验
          </Button>
          <Button variant="primary" loading={evaluating} onClick={() => onEvaluate(skill.id)}>
            <FlaskConical className="h-4 w-4" />
            LLM 评测
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={skill.status} />
          <DimensionBadge dimension={skill.dimension} />
          <Badge tone="neutral">v{skill.version}</Badge>
          <Badge tone="neutral">{skill.claim_ids.length} 条已批准断言</Badge>
          <Badge tone="neutral">{versionList.length} 个历史版本</Badge>
          {evalInfo ? <Badge tone="info">{evalInfo.mode === "llm" ? "LLM 评测" : "结构评测"} · {evalInfo.cases} 例</Badge> : null}
        </div>

        {staticReport ? (
          staticReport.ok ? (
            <Alert tone="success" title="静态校验通过">
              {staticReport.warnings?.length ? staticReport.warnings.join("；") : "结构、链接、隐私与评测用例检查均通过。"}
            </Alert>
          ) : (
            <Alert tone="danger" title="静态校验未通过">
              <ul className="mt-1 list-disc space-y-1 pl-4">
                {staticReport.errors?.map((error: string) => <li key={error}>{error}</li>)}
              </ul>
              {staticReport.warnings?.length ? (
                <p className="mt-2 opacity-80">警告：{staticReport.warnings.join("；")}</p>
              ) : null}
            </Alert>
          )
        ) : null}

        <Tabs
          items={[
            { value: "skill", label: "SKILL.md" },
            { value: "evidence", label: "证据参考" },
            { value: "evals", label: "评测用例" },
            { value: "history", label: "版本历史" },
            { value: "diff", label: "版本差异" },
          ]}
          value={tab}
          onChange={setTab}
        />

        {tab === "history" ? (
          <div className="space-y-2">
            {versions.isLoading ? (
              <div className="flex h-24 items-center justify-center"><Spinner /></div>
            ) : !versionList.length ? (
              <Alert tone="info" title="还没有版本快照">
                每次编译都会写入一个不可变快照。重新运行编译后即可在此比较差异。
              </Alert>
            ) : (
              versionList.map((version, index) => (
                <div key={version.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <Badge tone={index === 0 ? "primary" : "neutral"}>v{version.version}</Badge>
                    <span className="font-mono text-[10px] text-muted">{version.content_hash.slice(0, 12)}</span>
                    <span className="text-[10px] text-muted">{version.lines} 行 · {version.claim_ids.length} 条断言</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-muted">{formatDate(version.created_at)}</span>
                    {index < versionList.length - 1 ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          setDiffPair({ from: versionList[index + 1].version, to: version.version })
                        }
                      >
                        与上一版比较
                      </Button>
                    ) : null}
                  </div>
                </div>
              ))
            )}
          </div>
        ) : tab === "diff" ? (
          <div className="space-y-3">
            {diffPair ? (
              <>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone="neutral">v{diffPair.from} → v{diffPair.to}</Badge>
                  {diff.data ? (
                    <>
                      <Badge tone="success">+{diff.data.added_lines}</Badge>
                      <Badge tone="danger">−{diff.data.removed_lines}</Badge>
                      {diff.data.claims_added.length ? (
                        <Badge tone="info">新增断言 {diff.data.claims_added.length}</Badge>
                      ) : null}
                      {diff.data.claims_removed.length ? (
                        <Badge tone="warning">移除断言 {diff.data.claims_removed.length}</Badge>
                      ) : null}
                    </>
                  ) : null}
                </div>
                <CodeBlock code={content} />
              </>
            ) : (
              <Alert tone="info" title="选择两个版本">
                在“版本历史”中点击“与上一版比较”，即可查看 SKILL.md 的逐行差异与断言增删。
              </Alert>
            )}
          </div>
        ) : (
          <CodeBlock code={content} />
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-xl border p-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold"><Code2 className="h-3.5 w-3.5" /> 文件清单</p>
            <ul className="mt-2 space-y-1 text-[11px] text-muted">
              {Object.keys(files).map((file) => <li key={file} className="font-mono">{file}</li>)}
            </ul>
          </div>
          <div className="rounded-xl border p-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold"><ClipboardCheck className="h-3.5 w-3.5" /> 使用说明</p>
            <p className="mt-2 text-[11px] leading-5 text-muted">
              导出后将每个 Skill 目录安装到目标运行时的 skills 目录；references 与 evals 需一并保留。
              人物档案与知识库需要单独导入，不会由 SKILL.md 自动加载。
            </p>
          </div>
        </div>
      </div>
    </Modal>
  );
}
