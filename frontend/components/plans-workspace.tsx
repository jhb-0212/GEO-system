"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelRecord, PlanRecord } from "@/lib/workbench/types";

const planTypes = [["article", "图文"], ["video", "视频"]] as const;
const statuses = [["proposed", "已提议"], ["scheduled", "已排期"], ["in_production", "生产中"], ["pending_review", "待审核"], ["published", "已发布"], ["cancelled", "已取消"]] as const;
const label = (pairs: readonly (readonly [string, string])[], value: string) => pairs.find(([code]) => code === value)?.[1] ?? value;

interface Draft { title: string; plan_type: string; status: string; channel_id: string; scheduled_at: string; notes: string }
const blank = (): Draft => ({ title: "", plan_type: "article", status: "proposed", channel_id: "", scheduled_at: "", notes: "" });

export function PlansWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<PlanRecord[]>([]);
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.plans(projectId), workbenchClient.channels(projectId, 1, 100).catch(() => ({ data: [] as ChannelRecord[] }))])
      .then(([planResult, channelResult]) => {
        if (active) { setItems(planResult.data); setChannels(channelResult.data); setError(""); }
      }).catch((cause) => {
        if (active) { setItems([]); setError(cause instanceof Error ? cause.message : "计划加载失败"); }
      }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, canRead, projectId, version]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !canWrite) return;
    if (!draft.title.trim()) { onNotice("请填写计划标题"); return; }
    setSaving(true);
    try {
      await workbenchClient.savePlan(projectId, {
        title: draft.title.trim(),
        plan_type: draft.plan_type,
        status: draft.status,
        channel_id: draft.channel_id || null,
        scheduled_at: draft.scheduled_at ? new Date(draft.scheduled_at).toISOString() : null,
        notes: draft.notes.trim() || null,
      });
      setDraft(null);
      setVersion((value) => value + 1);
      onNotice("内容计划已保存");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setSaving(false); }
  }

  async function changeStatus(plan: PlanRecord, status: string) {
    if (!canWrite) return;
    try {
      await workbenchClient.savePlan(projectId, { status }, plan.id);
      setItems((rows) => rows.map((row) => row.id === plan.id ? { ...row, status } : row));
      onNotice(`计划状态已更新为 ${label(statuses, status)}`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "更新失败"); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">内容计划仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>内容计划与排期</h3><p>共 {items.length} 条计划 · 选题 → 生产 → 排期</p></div>{canWrite && <Button icon="plus" onClick={() => setDraft(blank())}>新增计划</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">
        {items.map((plan) => <div className="knowledge-item" key={plan.id}>
          <span><strong>{plan.title}</strong><small>{label(planTypes, plan.plan_type)} · {channels.find((c) => c.id === plan.channel_id)?.name ?? "未指定渠道"}{plan.owner_name ? ` · 负责人 ${plan.owner_name}` : ""}</small><small>排期：{plan.scheduled_at ? plan.scheduled_at.slice(0, 16).replace("T", " ") : "未排期"}</small></span>
          <span className="knowledge-actions">
            {canWrite ? (
              <select className="knowledge-filter" aria-label="更新计划状态" value={plan.status} onChange={(event) => void changeStatus(plan, event.target.value)}>
                {statuses.map(([code, text]) => <option value={code} key={code}>{text}</option>)}
              </select>
            ) : <Badge tone="slate">{label(statuses, plan.status)}</Badge>}
          </span>
        </div>)}
        {loading && !items.length && <p className="knowledge-empty">正在加载计划…</p>}
        {!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无内容计划。</p>}
      </div>
    </Panel>
    {draft && <Panel className="knowledge-editor-panel">
      <div className="panel-heading"><div><h3>新增内容计划</h3><p>排期与负责人可后补；逐步推进状态</p></div><Icon name="calendar" size={18}/></div>
      <form onSubmit={save}>
        <label className="field"><span className="field-label">计划标题</span><input className="text-input" value={draft.title} required maxLength={255} disabled={saving} onChange={(event) => setDraft({ ...draft, title: event.target.value })}/></label>
        <label className="field"><span className="field-label">类型</span><select className="text-input" value={draft.plan_type} disabled={saving} onChange={(event) => setDraft({ ...draft, plan_type: event.target.value })}>{planTypes.map(([code, text]) => <option value={code} key={code}>{text}</option>)}</select></label>
        <label className="field"><span className="field-label">渠道（可选）</span><select className="text-input" value={draft.channel_id} disabled={saving} onChange={(event) => setDraft({ ...draft, channel_id: event.target.value })}><option value="">不指定</option>{channels.map((channel) => <option value={channel.id} key={channel.id}>{channel.name}</option>)}</select></label>
        <label className="field"><span className="field-label">初始状态</span><select className="text-input" value={draft.status} disabled={saving} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>{statuses.map(([code, text]) => <option value={code} key={code}>{text}</option>)}</select></label>
        <label className="field"><span className="field-label">排期时间（可选）</span><input type="datetime-local" className="text-input" value={draft.scheduled_at} disabled={saving} onChange={(event) => setDraft({ ...draft, scheduled_at: event.target.value })}/></label>
        <label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" value={draft.notes} maxLength={5000} disabled={saving} onChange={(event) => setDraft({ ...draft, notes: event.target.value })}/></label>
        <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存计划"}</Button><Button variant="secondary" onClick={() => setDraft(null)}>取消</Button></div>
      </form>
    </Panel>}
  </div>;
}
