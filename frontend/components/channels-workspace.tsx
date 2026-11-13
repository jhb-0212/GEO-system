"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelRecord } from "@/lib/workbench/types";

const categories = [
  ["own_site", "自有站点"], ["content_platform", "内容平台"], ["video", "视频平台"],
  ["community", "社区"], ["encyclopedia", "百科"], ["local_media", "地方媒体"],
  ["industry_media", "行业媒体"], ["institution", "机构"],
] as const;
const statuses = [["candidate", "候选"], ["published", "已发布"], ["observed", "已观测"], ["review_pending", "待归类"]] as const;
const label = (pairs: readonly (readonly [string, string])[], value: string) => pairs.find(([code]) => code === value)?.[1] ?? value;

interface Draft { code: string; name: string; category: string; status: string; primary_domain: string; notes: string; aliases: string; is_active: boolean }
const blank = (): Draft => ({ code: "", name: "", category: "content_platform", status: "candidate", primary_domain: "", notes: "", aliases: "", is_active: true });

export function ChannelsWorkspace({ mode, projectId, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canWrite: boolean; onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<ChannelRecord[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadedKey, setLoadedKey] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [existingAliases, setExistingAliases] = useState<ChannelRecord["aliases"]>([]);

  const key = `${projectId}:${page}`;
  const loading = loadedKey !== key || detailLoading;
  useEffect(() => {
    if (mode !== "live" || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.channels(projectId, page).then((result) => {
      if (active) { setItems(result.data); setTotal(result.meta?.total ?? result.data.length); setError(""); setLoadedKey(key); }
    }).catch((cause) => { if (active) { setItems([]); setError(cause instanceof Error ? cause.message : "渠道加载失败"); setLoadedKey(key); } });
    return () => { active = false; };
  }, [mode, projectId, page, key]);

  async function openEdit(id: string) {
    if (!canWrite) return;
    setDetailLoading(true);
    try {
      const item = await workbenchClient.channel(projectId, id);
      if (item.is_active === undefined || item.aliases === undefined || item.notes === undefined) {
        throw new Error("当前后端尚未返回备注、启停和别名，不能安全编辑；请更新后端到前端联调分支");
      }
      setEditingId(id);
      setExistingAliases(item.aliases);
      setDraft({ code: item.code, name: item.name, category: item.category, status: item.status,
        primary_domain: item.primary_domain ?? "", notes: item.notes ?? "", aliases: "", is_active: item.is_active });
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "读取渠道详情失败"); }
    finally { setDetailLoading(false); }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !canWrite) return;
    setSaving(true);
    const aliases = [...new Set(draft.aliases.split(/[\n,，]+/).map((value) => value.trim().toLowerCase()).filter(Boolean))];
    const input: Record<string, unknown> = {
      name: draft.name.trim(), category: draft.category, status: draft.status,
      primary_domain: draft.primary_domain.trim() || null,
      notes: draft.notes.trim() || null, is_active: draft.is_active,
    };
    if (!editingId) input.code = draft.code.trim();
    if (aliases.length) input.aliases = aliases;
    try {
      await workbenchClient.saveChannel(projectId, input, editingId ?? undefined);
      const result = await workbenchClient.channels(projectId, page);
      setItems(result.data);
      setTotal(result.meta?.total ?? result.data.length);
      setDraft(null);
      setEditingId(null);
      onNotice("渠道已保存；旧名称和旧域名由后端保留为别名");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存渠道失败"); }
    finally { setSaving(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">渠道台账仅在真实接口模式显示。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>渠道台账</h3><p>项目渠道与归属域名，合计 {total} 条</p></div>{canWrite && <Button icon="plus" onClick={() => { setEditingId(null); setExistingAliases([]); setDraft(blank()); }}>新增渠道</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">{items.map((item) => <button className="knowledge-item" type="button" key={item.id} onClick={() => void openEdit(item.id)} disabled={!canWrite}><span><strong>{item.name}</strong><small>{item.code} · {item.primary_domain || "无主域名"}</small></span><span>{label(categories, item.category)} · {label(statuses, item.status)}</span><Badge tone={item.status === "review_pending" ? "amber" : "blue"}>{canWrite ? "编辑" : "只读"}</Badge></button>)}{!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无渠道</p>}{loading && <p className="knowledge-empty">正在加载渠道…</p>}</div>
      {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
    </Panel>
    {draft && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>{editingId ? "编辑渠道" : "新增渠道"}</h3><p>别名只能追加；旧名称和旧主域名由后端保存</p></div><Icon name="layers" size={18}/></div><form onSubmit={save}>
      <label className="field"><span className="field-label">代码</span><input className="text-input" value={draft.code} disabled={!!editingId || saving} required pattern="[a-z0-9][a-z0-9-]*" onChange={(event) => setDraft({ ...draft, code: event.target.value })}/></label>
      <label className="field"><span className="field-label">名称</span><input className="text-input" value={draft.name} disabled={saving} required maxLength={128} onChange={(event) => setDraft({ ...draft, name: event.target.value })}/></label>
      <label className="field"><span className="field-label">分类</span><select className="text-input" value={draft.category} disabled={saving} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>{categories.map(([code, text]) => <option value={code} key={code}>{text}</option>)}</select></label>
      <label className="field"><span className="field-label">状态</span><select className="text-input" value={draft.status} disabled={saving} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>{statuses.map(([code, text]) => <option value={code} key={code}>{text}</option>)}</select></label>
      <label className="field"><span className="field-label">主域名</span><input className="text-input" value={draft.primary_domain} disabled={saving} placeholder="example.com" onChange={(event) => setDraft({ ...draft, primary_domain: event.target.value })}/></label>
      <label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" value={draft.notes} disabled={saving} maxLength={5000} onChange={(event) => setDraft({ ...draft, notes: event.target.value })}/></label>
      {!!existingAliases?.length && <p className="knowledge-footnote">已有别名：{existingAliases.map((item) => item.domain).join("、")}</p>}
      <label className="field"><span className="field-label">新增别名域名（逗号或换行分隔）</span><textarea className="text-input knowledge-textarea short" value={draft.aliases} disabled={saving} onChange={(event) => setDraft({ ...draft, aliases: event.target.value })}/></label>
      <label className="rounds-checkbox"><input type="checkbox" checked={draft.is_active} disabled={saving} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}/> 启用渠道</label>
      <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存渠道"}</Button><Button variant="secondary" onClick={() => setDraft(null)}>取消</Button></div>
    </form></Panel>}
  </div>;
}
