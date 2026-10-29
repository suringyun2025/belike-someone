import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Boxes,
  CheckCircle2,
  Download,
  FileArchive,
  Info,
  ShieldCheck,
} from "lucide-react";
import { api } from "../../api";
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
  Spinner,
  StatusBadge,
} from "../../ui";
import { formatDate } from "../../lib/format";

const platforms = [
  ["通用", ".agents/skills/<name>/"],
  ["Claude Code", "~/.claude/skills 或项目 .claude/skills"],
  ["Codex", "按官方 Skills 文档"],
  ["Cursor", ".cursor/skills 或 .agents/skills"],
  ["Gemini CLI", "~/.gemini/skills 或 .agents/skills"],
  ["GitHub Copilot", ".github/skills"],
  ["Qoder", "~/.qoder/skills 或项目 .qoder/skills"],
];

export function ExportsTab({ project, setTab }: ProjectTabProps) {
  const exportsQuery = useQuery({
    queryKey: ["exports", project.id],
    queryFn: () => api.exports(project.id),
  });

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>人物模型包</CardTitle>
            <CardDescription>
              ZIP 包含 Skills、Persona Profile、知识索引、证据台账、评测结果、manifest 与兼容性说明；不包含 API Key 或原始私人全文。
            </CardDescription>
          </div>
          <Button variant="primary" onClick={() => setTab("pipeline")}>
            <Boxes className="h-4 w-4" />
            编译并导出 <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </CardHeader>
      </Card>

      {exportsQuery.isLoading ? (
        <div className="flex h-48 items-center justify-center"><Spinner /></div>
      ) : !exportsQuery.data?.length ? (
        <Card>
          <EmptyState
            icon={<FileArchive className="h-5 w-5" />}
            title="还没有导出包"
            description="先批准断言并运行编译任务；编译会完成校验、评测与打包。"
            action={<Button variant="primary" onClick={() => setTab("skills")}>查看 Skills</Button>}
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {exportsQuery.data.map((item) => (
            <Card key={item.id} className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <FileArchive className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold">{item.manifest?.package || "人物模型包"}</h3>
                      <StatusBadge status={item.status} />
                    </div>
                    <p className="mt-1 font-mono text-[10px] text-muted">{item.id} · {formatDate(item.created_at)}</p>
                  </div>
                </div>
                <a
                  href={api.exportDownloadUrl(item.id)}
                  className="btn btn-primary"
                  download
                >
                  <Download className="h-4 w-4" />
                  下载 ZIP
                </a>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <PackageMetric label="Skills" value={item.manifest?.skills?.length || 0} />
                <PackageMetric label="资料" value={item.manifest?.sources?.length || 0} />
                <PackageMetric label="已批准断言" value={item.manifest?.review?.approved_claims || 0} />
                <PackageMetric label="待审核断言" value={item.manifest?.review?.pending_claims || 0} />
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {(item.manifest?.skills || []).map((skill: any) => (
                  <Badge key={skill.name} tone="neutral">{skill.name}</Badge>
                ))}
              </div>
              <div className="mt-4 flex items-start gap-2 rounded-xl border border-border bg-elevated/40 p-3 text-[11px] leading-5 text-muted">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                包内 README 说明各平台的安装目录。格式兼容不等于行为兼容；安装后请实际验证技能发现、触发与 references 加载。
              </div>
            </Card>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>包内结构</CardTitle>
              <CardDescription>四类资产分开存放，便于平台适配</CardDescription>
            </div>
            <ShieldCheck className="h-4 w-4 text-muted" />
          </CardHeader>
          <CardContent className="pt-0">
            <pre className="overflow-auto rounded-xl border bg-elevated p-4 font-mono text-[11px] leading-6 text-muted">{`person-package/
├── manifest.json
├── README.md
├── persona/
├── decision-model/
├── skills/
│   └── <name>/
│       ├── SKILL.md
│       ├── references/
│       └── evals/
├── knowledge/
├── provenance/
├── evaluations/
└── compatibility/`}</pre>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>目标平台</CardTitle>
              <CardDescription>安装目录以各平台当前版本文档为准</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {platforms.map(([name, path]) => (
              <div key={name} className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                <span className="text-xs font-medium">{name}</span>
                <span className="text-right font-mono text-[10px] text-muted">{path}</span>
              </div>
            ))}
            <Alert tone="warning" className="mt-2">
              至少对 2 个运行时做真实安装/调用测试；未实测的平台应标注“结构校验通过、行为待验证”。
            </Alert>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function PackageMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-elevated/40 px-3 py-2">
      <p className="text-[10px] text-muted">{label}</p>
      <p className="mt-0.5 text-sm font-semibold">{value}</p>
    </div>
  );
}
