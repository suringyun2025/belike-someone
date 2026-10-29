import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ClipboardList,
  FlaskConical,
  Play,
  ShieldCheck,
} from "lucide-react";
import { api } from "../../api";
import type { EvalRun } from "../../types";
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
  EmptyState,
  Modal,
  Select,
  Spinner,
  StatusBadge,
  useToast,
} from "../../ui";
import { formatDate, truncate } from "../../lib/format";

export function EvalsTab({ project, providers, setTab }: ProjectTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null);
  const [generatorId, setGeneratorId] = useState(project.provider_id || "");
  const [judgeId, setJudgeId] = useState(project.provider_id || "");
  const [maxCases, setMaxCases] = useState("10");
  const skills = useQuery({ queryKey: ["skills", project.id], queryFn: () => api.skills(project.id) });

  useEffect(() => {
    const fallback = project.provider_id || providers[0]?.id || "";
    if (!generatorId) setGeneratorId(fallback);
    if (!judgeId) setJudgeId(fallback);
  }, [project.provider_id, providers, generatorId, judgeId]);
  const cases = useQuery({ queryKey: ["eval-cases", project.id], queryFn: () => api.evalCases(project.id) });
  const runs = useQuery({ queryKey: ["eval-runs", project.id], queryFn: () => api.evalRuns(project.id) });
  const skillMap = useMemo(
    () => new Map((skills.data || []).map((skill) => [skill.id, skill])),
    [skills.data],
  );

  const evaluate = useMutation({
    mutationFn: (skillId: string) => {
      if (!generatorId || !judgeId) throw new Error("请选择生成模型与评审模型");
      return api.evaluateSkill(skillId, {
        provider_id: generatorId,
        judge_provider_id: judgeId,
        max_cases: Number(maxCases) || 10,
      });
    },
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["eval-runs", project.id] });
      queryClient.invalidateQueries({ queryKey: ["eval-cases", project.id] });
      toast({ title: "LLM-as-judge 已完成", description: run.report, variant: "success" });
    },
    onError: (error: Error) => toast({ title: "评测失败", description: error.message, variant: "error" }),
  });

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <EvalStat label="评测用例" value={cases.data?.length || 0} icon={<ClipboardList className="h-4 w-4" />} />
        <EvalStat label="评测运行" value={runs.data?.length || 0} icon={<FlaskConical className="h-4 w-4" />} />
        <EvalStat label="已校验 Skills" value={(skills.data || []).filter((skill) => skill.status === "validated" || skill.status === "exported").length} icon={<ShieldCheck className="h-4 w-4" />} />
      </div>

      <Card>
        <CardContent className="grid grid-cols-1 items-end gap-3 p-4 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_120px_auto]">
          <label>
            <span className="label">生成模型</span>
            <Select value={generatorId} onChange={(event) => setGeneratorId(event.target.value)}>
              <option value="">选择 Provider</option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name} · {provider.model_id}
                </option>
              ))}
            </Select>
          </label>
          <label>
            <span className="label">评审模型（LLM-as-judge）</span>
            <Select value={judgeId} onChange={(event) => setJudgeId(event.target.value)}>
              <option value="">选择 Provider</option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name} · {provider.model_id}
                </option>
              ))}
            </Select>
          </label>
          <label>
            <span className="label">最大用例</span>
            <Select value={maxCases} onChange={(event) => setMaxCases(event.target.value)}>
              <option value="5">5</option>
              <option value="10">10</option>
              <option value="20">20</option>
            </Select>
          </label>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => setTab("pipeline")}>
              编译时启用 <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </div>
          {!providers.length ? (
            <div className="col-span-4">
              <Alert tone="warning" title="需要 Provider">
                先在“模型与 API”配置生成模型与评审模型，才能运行 LLM-as-judge。
              </Alert>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Skills 评测</CardTitle>
            <CardDescription>
              触发判断单独评分；回答按任务完成、证据忠实、人格保真、边界合规四维 rubric 评分，并由评审模型给出通过/不通过。
            </CardDescription>
          </div>
          <Button variant="ghost" onClick={() => setTab("pipeline")}>
            去流水线运行 <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </CardHeader>
        <CardContent className="pt-0">
          {skills.isLoading ? (
            <div className="flex h-32 items-center justify-center"><Spinner /></div>
          ) : !skills.data?.length ? (
            <EmptyState
              icon={<FlaskConical className="h-5 w-5" />}
              title="还没有可评测的 Skills"
              description="先审核断言并编译 Skills。"
              action={<Button variant="primary" onClick={() => setTab("skills")}>查看 Skills</Button>}
            />
          ) : (
            <div className="space-y-2">
              {skills.data.map((skill) => (
                <div key={skill.id} className="flex items-center gap-3 rounded-xl border px-3 py-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-elevated text-muted">
                    <FlaskConical className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium">{skill.title}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-muted">{skill.name} · v{skill.version}</p>
                  </div>
                  <Badge tone="neutral">{skill.claim_ids.length} 条断言</Badge>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={evaluate.isPending}
                    disabled={!generatorId || !judgeId}
                    onClick={() => evaluate.mutate(skill.id)}
                  >
                    <Play className="h-3.5 w-3.5" />
                    LLM 评测
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>评测运行</CardTitle>
            <CardDescription>每次运行保存用例、模式和结果，便于回归对比</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {runs.isLoading ? (
            <div className="flex h-32 items-center justify-center"><Spinner /></div>
          ) : !runs.data?.length ? (
            <EmptyState
              icon={<ClipboardList className="h-5 w-5" />}
              title="还没有评测运行"
              description="对任意 Skill 点击“生成评测”，或在编译任务中启用 LLM 评测。"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Skill</th>
                    <th>模式</th>
                    <th>用例</th>
                    <th>Overall</th>
                    <th>Pass</th>
                    <th>Trigger</th>
                    <th>状态</th>
                    <th>时间</th>
                    <th className="text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.map((run) => (
                    <tr key={run.id}>
                      <td className="text-xs font-medium">{skillMap.get(run.skill_id)?.name || run.skill_id}</td>
                      <td><Badge tone={run.results?.mode === "llm-judge" ? "success" : "info"}>{run.results?.mode || "structural"}</Badge></td>
                      <td className="text-xs">{run.results?.metrics?.cases ?? run.results?.cases?.length ?? 0}</td>
                      <td className="font-mono text-xs">{run.results?.metrics?.overall_score ?? "—"}</td>
                      <td className="font-mono text-xs">{run.results?.metrics?.pass_rate ?? "—"}</td>
                      <td className="font-mono text-xs">{run.results?.metrics?.trigger_accuracy ?? "—"}</td>
                      <td><StatusBadge status={run.status} /></td>
                      <td className="text-xs text-muted">{formatDate(run.created_at)}</td>
                      <td>
                        <div className="flex justify-end">
                          <Button size="sm" variant="ghost" onClick={() => setSelectedRun(run)}>查看结果</Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>测试用例</CardTitle>
            <CardDescription>触发、任务完成、边界与泛化用例</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {!cases.data?.length ? (
            <Alert tone="info">编译 Skills 或点击“生成评测”后，会在这里看到用例。</Alert>
          ) : (
            <div className="max-h-80 overflow-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Skill</th>
                    <th>类别</th>
                    <th>Prompt</th>
                    <th>预期</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.data.map((item) => (
                    <tr key={item.id}>
                      <td className="text-xs">{skillMap.get(item.skill_id || "")?.name || "—"}</td>
                      <td><Badge tone={item.category === "positive" ? "success" : "warning"}>{item.category}</Badge></td>
                      <td className="max-w-md text-xs text-muted">{truncate(item.prompt, 120)}</td>
                      <td className="max-w-md text-xs text-muted">{truncate(item.expected, 100)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Modal
        open={Boolean(selectedRun)}
        onClose={() => setSelectedRun(null)}
        title="评测结果"
        description={selectedRun ? `${skillMap.get(selectedRun.skill_id)?.name || selectedRun.skill_id} · ${selectedRun.report}` : ""}
        size="xl"
      >
        {selectedRun ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <RunMetric label="Overall" value={selectedRun.results?.metrics?.overall_score ?? "—"} />
              <RunMetric label="Pass rate" value={selectedRun.results?.metrics?.pass_rate ?? "—"} />
              <RunMetric label="Trigger acc." value={selectedRun.results?.metrics?.trigger_accuracy ?? "—"} />
              <RunMetric label="Errors" value={selectedRun.results?.metrics?.errors ?? "—"} />
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <RunMetric label="任务完成" value={selectedRun.results?.metrics?.avg_task_completion ?? "—"} />
              <RunMetric label="证据忠实" value={selectedRun.results?.metrics?.avg_evidence_fidelity ?? "—"} />
              <RunMetric label="人格保真" value={selectedRun.results?.metrics?.avg_persona_fidelity ?? "—"} />
              <RunMetric label="边界合规" value={selectedRun.results?.metrics?.avg_boundary_compliance ?? "—"} />
            </div>
            <CodeBlock code={JSON.stringify(selectedRun.results, null, 2)} />
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

function RunMetric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-elevated/40 p-3">
      <p className="text-[10px] uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-1 font-mono text-lg font-semibold">{value}</p>
    </div>
  );
}

function EvalStat({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <div className="rounded-xl bg-primary/10 p-2 text-primary">{icon}</div>
      <div>
        <p className="text-[10px] uppercase tracking-wider text-muted">{label}</p>
        <p className="text-xl font-semibold">{value}</p>
      </div>
    </Card>
  );
}
