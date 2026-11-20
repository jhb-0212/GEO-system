"use client";

import { useEffect, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { Badge, Button, Icon, Panel, TextInput } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
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
  if (result.complete) return { title: "任务生成完整", detail: `${result.generated_task_count} 个任务已建立或复用；采样结果需要另行查看。`, tone: "green" };
  if (result.skipped_reason === "question_version_missing") return { title: "整批未生成", detail: "有启用题目缺少当前版本，需先修复题目数据。", tone: "red" };
  if (result.skipped_reason === "engine_entries_insufficient") return { title: "引擎入口不足", detail: "只对当前可用的启用入口生成任务，可补齐后再次生成。", tone: "amber" };
  return { title: "只生成了一部分", detail: "草稿或归档题目未进入正式任务，可激活后再次生成。", tone: "amber" };
}

export function MonitoringRounds({ mode, projectId, projects, rounds, setRounds, generatedKeys, setGeneratedKeys, canExecute, onNotice, onGenerated }: {
  mode: "mock" | "live";
  projectId: string;
  projects: Project[];
  rounds: MonitoringRound[];
  setRounds: Dispatch<SetStateAction<MonitoringRound[]>>;
  generatedKeys: string[];
  setGeneratedKeys: Dispatch<SetStateAction<string[]>>;
  canExecute: boolean;
  onNotice: (message: string) => void;
  onGenerated?: () => void;
}) {
  const [selectedRoundId, setSelectedRoundId] = useState(() => rounds[0]?.id ?? "");
  const [name, setName] = useState("");
  const [baseline, setBaseline] = useState(false);
  const [scenario, setScenario] = useState<Scenario>("complete");
  const [result, setResult] = useState<BatchGenerationResult | null>(null);
  const [liveRounds, setLiveRounds] = useState<MonitoringRound[]>([]);
  const [liveTotal, setLiveTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [loadError, setLoadError] = useState("");
  const activeProject = projectId === "all" ? projects[0]?.id : projectId;
  useEffect(() => {
    if (mode !== "live" || !activeProject) return;
    let active = true;
    workbenchClient.rounds(activeProject, page).then((response) => {
      if (!active) return;
      setLiveRounds(response.data);
      setLiveTotal(response.meta?.total ?? response.data.length);
      setLoadError("");
    }).catch((error) => { if (active) { setLiveRounds([]); setLoadError(error instanceof Error ? error.message : "轮次加载失败"); } });
    return () => { active = false; };
  }, [mode, activeProject, page]);
  const visibleRounds = mode === "mock" ? rounds.filter((round) => round.project_id === activeProject).sort((a, b) => b.seq - a.seq) : liveRounds;
  const selectedRound = visibleRounds.find((round) => round.id === selectedRoundId) ?? visibleRounds[0];

  async function createRound(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeProject || !name.trim()) { onNotice("请先选择项目并输入轮次名称"); return; }
    if (mode === "live") {
      if (!canExecute) { onNotice("当前账号没有创建轮次的权限"); return; }
      setBusy(true);
      try {
        const created = await workbenchClient.createRound(activeProject, { name: name.trim(), is_baseline: baseline });
        setSelectedRoundId(created.id);
        setName("");
        setShowCreate(false);
        setResult(null);
        const response = await workbenchClient.rounds(activeProject, page);
        setLiveRounds(response.data);
        setLiveTotal(response.meta?.total ?? response.data.length);
        onNotice(created.is_baseline ? "基线轮次已创建或复用" : "轮次已创建");
      } catch (error) { onNotice(error instanceof Error ? error.message : "创建轮次失败"); }
      finally { setBusy(false); }
      return;
    }
    const existing = baseline ? rounds.find((round) => round.project_id === activeProject && round.is_baseline) : undefined;
    if (existing) {
      setSelectedRoundId(existing.id);
      setShowCreate(false);
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
    setShowCreate(false);
    onNotice("轮次只添加到了当前页面，未写入服务器");
  }

  async function generate() {
    if (!selectedRound || !activeProject) { onNotice("请先选择轮次"); return; }
    if (mode === "live") {
      if (!canExecute) { onNotice("当前账号没有生成任务的权限"); return; }
      setBusy(true);
      try {
        const next = await workbenchClient.generateTasks(activeProject, selectedRound.id);
        setResult(next);
        onGenerated?.();
        onNotice(next.complete ? `已生成或复用 ${next.generated_task_count} 个任务` : `仅生成或复用 ${next.generated_task_count} 个任务，请查看原因`);
      } catch (error) { onNotice(error instanceof Error ? error.message : "生成任务失败"); }
      finally { setBusy(false); }
      return;
    }
    const key = `${selectedRound.id}:${scenario}`;
    const next = demoBatch(selectedRound.id, scenario, generatedKeys.includes(key));
    setResult(next);
    if (!generatedKeys.includes(key) && next.generated_task_count > 0) setGeneratedKeys((current) => [...current, key]);
    onNotice(next.reused_task_count > 0 ? "重复生成：复用已有演示任务，没有新增" : "已显示演示生成结果，未写入服务器");
  }

  async function completeSelectedRound() {
    if (!selectedRound || !activeProject) { onNotice("请先选择轮次"); return; }
    if (mode !== "live") { onNotice("演示模式不会保存统计结果"); return; }
    if (!canExecute) { onNotice("当前账号没有完成轮次的权限"); return; }
    setBusy(true);
    try {
      await workbenchClient.completeRound(activeProject, selectedRound.id);
      const response = await workbenchClient.rounds(activeProject, page);
      setLiveRounds(response.data);
      setLiveTotal(response.meta?.total ?? response.data.length);
      onNotice("本轮已完成，统计结果已保存");
    } catch (error) { onNotice(error instanceof Error ? error.message : "完成轮次失败"); }
    finally { setBusy(false); }
  }

  const visibleResult = result?.round_id === selectedRound?.id ? result : null;
  const summary = visibleResult ? resultCopy(visibleResult) : null;
  return <div className="rounds-workspace">
    <div className="knowledge-notice" role="note"><Icon name="info" size={18}/><div><strong>{mode === "mock" ? "轮次与批量生成 · 前端演示" : "轮次与批量生成"}</strong><p>{mode === "mock" ? "演示轮次只保留在当前浏览器页签，不会写入服务器。生成任务不等于采样成功，也不代表已有有效回答。" : "轮次和任务会保存到系统；生成任务不代表采样成功，运行后请查看结果。"}</p></div></div>
    <div className="rounds-grid">
      <Panel className="rounds-panel">
        <div className="panel-heading"><div><h3>监测轮次</h3><p>按项目查看计划与基线轮次</p></div><Badge tone={mode === "mock" ? "amber" : "blue"}>{mode === "mock" ? "演示记录" : "真实数据"}</Badge></div>
        {loadError && <p className="form-error" role="alert">{loadError}</p>}
        <div className="rounds-list">{visibleRounds.map((round) => <button key={round.id} type="button" className={`rounds-item ${selectedRound?.id === round.id ? "selected" : ""}`} onClick={() => { setSelectedRoundId(round.id); setResult(null); }}><span><strong>第 {round.seq} 轮 · {round.name}</strong><small>{mode === "mock" ? round.created_at : round.created_at ? new Date(round.created_at).toLocaleString("zh-CN") : "时间未记录"} · {round.status === "planning" ? "计划中" : round.status === "draft" ? "草稿" : round.status === "running" ? "执行中" : round.status === "completed" ? "已完成" : round.status === "closed" ? "已关闭" : round.status}</small></span>{round.is_baseline && <Badge tone="blue">基线</Badge>}</button>)}{!visibleRounds.length && !loadError && <p className="knowledge-empty">{mode === "mock" ? "这个项目还没有演示轮次，可以在右侧新建" : "当前项目暂无轮次"}</p>}</div>
        {mode === "live" && liveTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(liveTotal / 20)}</span><Button variant="secondary" disabled={page * 20 >= liveTotal} onClick={() => setPage(page + 1)}>下一页</Button></div>}
      </Panel>
      <div className="rounds-side">
        <Panel className="rounds-panel"><div className="panel-heading"><div><h3>新建轮次</h3><p>已有基线轮次会直接复用</p></div><Icon name="plus" size={18}/></div><div className="knowledge-actions"><Button icon="plus" disabled={!canExecute} onClick={() => setShowCreate(true)}>新建轮次</Button></div></Panel>
        <Panel className="rounds-panel"><div className="panel-heading"><div><h3>批量生成任务</h3><p>{selectedRound ? `当前选择：第 ${selectedRound.seq} 轮` : "请先选择轮次"}</p></div><Icon name="pulse" size={18}/></div>{mode === "mock" && <label className="field"><span className="field-label">演示结果情形</span><select className="text-input" value={scenario} onChange={(event) => { setScenario(event.target.value as Scenario); setResult(null); }}><option value="complete">6 题 × 4 引擎，完整生成 24 条</option><option value="inactive">2 题未激活，部分生成 16 条</option><option value="missing_version">题目缺版本，整批生成 0 条</option><option value="few_engines">只有 3 个引擎，部分生成 18 条</option></select></label>}<Button onClick={generate} disabled={busy || !selectedRound || !canExecute} className="rounds-generate">{mode === "mock" ? "生成任务（演示）" : "生成任务"}</Button><p className="knowledge-footnote">重复生成会复用已有任务；实际采样结果另行查看。</p></Panel>
        {mode === "live" && selectedRound && <Panel className="rounds-panel"><div className="panel-heading"><div><h3>完成本轮并冻结</h3><p>当前状态：{selectedRound.status === "planning" ? "计划中" : selectedRound.status === "running" ? "执行中" : selectedRound.status === "completed" ? "已完成" : "已关闭"}</p></div><Icon name="check" size={18}/></div><Button disabled={busy || !canExecute || selectedRound.status !== "running"} onClick={() => void completeSelectedRound()}>{busy ? "处理中…" : selectedRound.status === "completed" ? "已完成，快照已冻结" : "完成本轮并冻结"}</Button><p className="knowledge-footnote">完成前会校验所有任务都已成功；存在失败、不确定或已取消任务时不能冻结。</p></Panel>}
      </div>
    </div>
    {showCreate && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setShowCreate(false); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="round-create-title" style={{ maxHeight: "88vh", overflowY: "auto" }}>
        <div className="modal-header"><div><p className="eyebrow">MONITORING ROUND</p><h2 id="round-create-title">新建轮次</h2></div><button className="icon-button" aria-label="关闭" disabled={busy} onClick={() => setShowCreate(false)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">已有基线轮次会直接复用。</p>
        <form onSubmit={createRound} className="rounds-form">
          <TextInput label="轮次名称" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：11 月首期监测" disabled={busy || !canExecute}/>
          <label className="rounds-checkbox"><input type="checkbox" checked={baseline} onChange={(event) => setBaseline(event.target.checked)} disabled={busy || !canExecute}/> 作为项目基线轮次</label>
          <div className="modal-actions"><Button type="submit" disabled={busy || !canExecute}>{mode === "mock" ? "新建轮次（演示）" : "新建轮次"}</Button><Button variant="secondary" disabled={busy} onClick={() => setShowCreate(false)}>取消</Button></div>
        </form>
      </div>
    </div>}
    {visibleResult && summary && <Panel className={`rounds-result rounds-result-${summary.tone}`}><div className="panel-heading"><div><h3>{summary.title}</h3><p>{summary.detail}</p></div><Badge tone={summary.tone}>{visibleResult.complete ? "完整" : "未完整"}</Badge></div><div className="rounds-result-numbers"><div><span>计划任务</span><strong>{visibleResult.expected_task_count}</strong></div><div><span>实际生成或复用</span><strong>{visibleResult.generated_task_count}</strong></div><div><span>本次新建</span><strong>{visibleResult.created_task_count}</strong></div><div><span>复用已有</span><strong>{visibleResult.reused_task_count}</strong></div></div><p className="rounds-result-detail">题目：可用 {visibleResult.eligible_question_count}/{visibleResult.requested_question_count}；引擎：{visibleResult.engine_count}/4。{visibleResult.skipped_reason && `原因：${visibleResult.skipped_reason}。`}</p>{visibleResult.inactive_questions.length > 0 && <p className="rounds-result-detail">未激活：{visibleResult.inactive_questions.map((item) => `${item.code}（${item.status}）`).join("、")}</p>}{visibleResult.question_version_missing_count > 0 && <p className="rounds-result-detail">缺少当前版本的题目 ID：{visibleResult.question_version_missing_question_ids.join("、")}</p>}<p className="rounds-result-foot">这只是任务生成结果；没有有效样本时，品牌提及率与引用率应显示“暂无有效数据”，不显示 0%。</p></Panel>}
  </div>;
}
