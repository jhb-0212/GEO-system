"use client";

import { useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { Badge, Button, Icon, Panel, TextInput } from "./ui";
import type { BatchGenerationResult, MonitoringRound, Project } from "@/lib/workbench/types";

type Scenario = "complete" | "inactive" | "missing_version" | "few_engines";

export const initialDemoRounds: MonitoringRound[] = [{
  id: "round-demo-1", project_id: "p-gz", seq: 1, name: "广州基地 · 首期技术基线",
  is_baseline: true, status: "draft", planned_at: null, created_at: "演示记录",
}];

function demoBatch(roundId: string, scenario: Scenario, replay: boolean): BatchGenerationResult {
  const inactive = scenario === "inactive";
  const missing = scenario === "missing_version";
  const engineCount = scenario === "few_engines" ? 3 : 4;
  const eligible = inactive ? 4 : missing ? 5 : 6;
  const generated = missing ? 0 : eligible * engineCount;
  return {
    round_id: roundId,
    requested_question_count: 6,
    eligible_question_count: eligible,
    inactive_question_count: inactive ? 2 : 0,
    inactive_question_ids: inactive ? ["question-q05", "question-q06"] : [],
    inactive_questions: inactive ? [
      { id: "question-q05", code: "Q05", title: "学完 AIGC 能应聘什么岗位？", status: "draft" },
      { id: "question-q06", code: "Q06", title: "广州 AI 实训怎么收费？", status: "archived" },
    ] : [],
    question_version_missing_count: missing ? 1 : 0,
    question_version_missing_question_ids: missing ? ["question-q03"] : [],
    engine_count: engineCount,
    expected_task_count: 6 * engineCount,
    eligible_expected_task_count: eligible * engineCount,
    created_task_count: replay ? 0 : generated,
    reused_task_count: replay ? generated : 0,
    generated_task_count: generated,
    complete: scenario === "complete",
    skipped_reason: missing ? "question_version_missing" : scenario === "few_engines" ? "engine_entries_insufficient" : inactive ? "inactive_questions" : null,
  };
}

function resultCopy(result: BatchGenerationResult): { title: string; detail: string; tone: "green" | "amber" | "red" } {
  if (result.complete) return { title: "任务生成完整", detail: "24 个任务已建立或复用；采样结果需要另行查看。", tone: "green" };
  if (result.skipped_reason === "question_version_missing") return { title: "整批未生成", detail: "有启用题目缺少当前版本，需先修复题目数据。", tone: "red" };
  if (result.skipped_reason === "engine_entries_insufficient") return { title: "引擎入口不足", detail: "只对当前可用的启用入口生成任务，可补齐后再次生成。", tone: "amber" };
  return { title: "只生成了一部分", detail: "草稿或归档题目未进入正式任务，可激活后再次生成。", tone: "amber" };
}

export function MonitoringRounds({ mode, projectId, projects, rounds, setRounds, generatedKeys, setGeneratedKeys, onNotice }: {
  mode: "mock" | "live";
  projectId: string;
  projects: Project[];
  rounds: MonitoringRound[];
  setRounds: Dispatch<SetStateAction<MonitoringRound[]>>;
  generatedKeys: string[];
  setGeneratedKeys: Dispatch<SetStateAction<string[]>>;
  onNotice: (message: string) => void;
}) {
  const [selectedRoundId, setSelectedRoundId] = useState(() => rounds[0]?.id ?? "");
  const [name, setName] = useState("");
  const [baseline, setBaseline] = useState(false);
  const [scenario, setScenario] = useState<Scenario>("complete");
  const [result, setResult] = useState<BatchGenerationResult | null>(null);
  const activeProject = projectId === "all" ? projects[0]?.id : projectId;
  const visibleRounds = mode === "mock" ? rounds.filter((round) => round.project_id === activeProject).sort((a, b) => b.seq - a.seq) : [];
  const selectedRound = visibleRounds.find((round) => round.id === selectedRoundId) ?? visibleRounds[0];

  function createRound(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode !== "mock") { onNotice("轮次接口尚未交付，未创建真实轮次"); return; }
    if (!activeProject || !name.trim()) { onNotice("请先选择项目并输入轮次名称"); return; }
    const existing = baseline ? rounds.find((round) => round.project_id === activeProject && round.is_baseline) : undefined;
    if (existing) {
      setSelectedRoundId(existing.id);
      setResult(null);
      onNotice("已选择现有的基线轮次，没有重复创建（演示）");
      return;
    }
    const round: MonitoringRound = {
      id: `round-demo-${Date.now()}`, project_id: activeProject,
      seq: Math.max(0, ...rounds.filter((item) => item.project_id === activeProject).map((item) => item.seq)) + 1,
      name: name.trim(), is_baseline: baseline, status: "draft", planned_at: null, created_at: "刚刚 · 演示",
    };
    setRounds((current) => [round, ...current]);
    setSelectedRoundId(round.id);
    setResult(null);
    setName("");
    onNotice("轮次只添加到了当前页面，未写入服务器");
  }

  function generate() {
    if (mode !== "mock" || !selectedRound) { onNotice("批量生成接口尚未交付，未创建真实任务"); return; }
    const key = `${selectedRound.id}:${scenario}`;
    const next = demoBatch(selectedRound.id, scenario, generatedKeys.includes(key));
    setResult(next);
    if (!generatedKeys.includes(key) && next.generated_task_count > 0) setGeneratedKeys((current) => [...current, key]);
    onNotice(next.reused_task_count > 0 ? "重复生成：复用已有演示任务，没有新增" : "已显示演示生成结果，未写入服务器");
  }

  const visibleResult = result?.round_id === selectedRound?.id ? result : null;
  const summary = visibleResult ? resultCopy(visibleResult) : null;
  return <div className="rounds-workspace">
    <div className="knowledge-notice" role="note"><Icon name="info" size={18}/><div><strong>{mode === "mock" ? "轮次与批量生成 · 前端演示" : "轮次与批量生成 · 等待 B4 接口"}</strong><p>{mode === "mock" ? "演示轮次只保留在当前浏览器页签，不会写入服务器。生成任务不等于采样成功，也不代表已有有效回答。" : "后端三个轮次接口尚未交付；这里不会显示演示记录或假装创建成功。"}</p></div></div>
    <div className="rounds-grid">
      <Panel className="rounds-panel">
        <div className="panel-heading"><div><h3>监测轮次</h3><p>按项目查看计划与基线轮次</p></div><Badge tone={mode === "mock" ? "amber" : "slate"}>{mode === "mock" ? "演示记录" : "待接接口"}</Badge></div>
        <div className="rounds-list">{visibleRounds.map((round) => <button key={round.id} type="button" className={`rounds-item ${selectedRound?.id === round.id ? "selected" : ""}`} onClick={() => { setSelectedRoundId(round.id); setResult(null); }}><span><strong>第 {round.seq} 轮 · {round.name}</strong><small>{round.created_at} · {round.status === "draft" ? "草稿" : round.status}</small></span>{round.is_baseline && <Badge tone="blue">基线</Badge>}</button>)}{!visibleRounds.length && <p className="knowledge-empty">{mode === "mock" ? "这个项目还没有演示轮次，可以在右侧新建" : "轮次接口尚未交付，暂无真实轮次"}</p>}</div>
      </Panel>
      <div className="rounds-side">
        <Panel className="rounds-panel"><div className="panel-heading"><div><h3>新建轮次</h3><p>已有基线轮次会直接复用</p></div><Icon name="plus" size={18}/></div><form onSubmit={createRound} className="rounds-form"><TextInput label="轮次名称" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：11 月首期监测" disabled={mode !== "mock"}/><label className="rounds-checkbox"><input type="checkbox" checked={baseline} onChange={(event) => setBaseline(event.target.checked)} disabled={mode !== "mock"}/> 作为项目基线轮次</label><Button type="submit" disabled={mode !== "mock"}>新建轮次（演示）</Button></form></Panel>
        <Panel className="rounds-panel"><div className="panel-heading"><div><h3>批量生成任务</h3><p>{selectedRound ? `当前选择：第 ${selectedRound.seq} 轮` : "请先选择轮次"}</p></div><Icon name="pulse" size={18}/></div><label className="field"><span className="field-label">演示结果情形</span><select className="text-input" value={scenario} onChange={(event) => { setScenario(event.target.value as Scenario); setResult(null); }} disabled={mode !== "mock"}><option value="complete">6 题 × 4 引擎，完整生成 24 条</option><option value="inactive">2 题未激活，部分生成 16 条</option><option value="missing_version">题目缺版本，整批生成 0 条</option><option value="few_engines">只有 3 个引擎，部分生成 18 条</option></select></label><Button onClick={generate} disabled={mode !== "mock" || !selectedRound} className="rounds-generate">生成任务（演示）</Button><p className="knowledge-footnote">重复点击同一情形会显示“复用已有任务”，不会当成错误。</p></Panel>
      </div>
    </div>
    {visibleResult && summary && <Panel className={`rounds-result rounds-result-${summary.tone}`}><div className="panel-heading"><div><h3>{summary.title}</h3><p>{summary.detail}</p></div><Badge tone={summary.tone}>{visibleResult.complete ? "完整" : "未完整"}</Badge></div><div className="rounds-result-numbers"><div><span>计划任务</span><strong>{visibleResult.expected_task_count}</strong></div><div><span>实际生成或复用</span><strong>{visibleResult.generated_task_count}</strong></div><div><span>本次新建</span><strong>{visibleResult.created_task_count}</strong></div><div><span>复用已有</span><strong>{visibleResult.reused_task_count}</strong></div></div><p className="rounds-result-detail">题目：可用 {visibleResult.eligible_question_count}/{visibleResult.requested_question_count}；引擎：{visibleResult.engine_count}/4。{visibleResult.skipped_reason && `原因：${visibleResult.skipped_reason}。`}</p>{visibleResult.inactive_questions.length > 0 && <p className="rounds-result-detail">未激活：{visibleResult.inactive_questions.map((item) => `${item.code}（${item.status}）`).join("、")}</p>}{visibleResult.question_version_missing_count > 0 && <p className="rounds-result-detail">缺少当前版本的题目 ID：{visibleResult.question_version_missing_question_ids.join("、")}</p>}<p className="rounds-result-foot">这只是任务生成结果；没有有效样本时，品牌提及率与引用率应显示“暂无有效数据”，不显示 0%。</p></Panel>}
  </div>;
}
