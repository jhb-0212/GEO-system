"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { SiteModuleRecord, SiteRecord } from "@/lib/workbench/types";

const MODULE_LABEL: Record<SiteModuleRecord["module_type"], string> = {
  home: "首页",
  services: "产品服务",
  news: "资讯",
  download: "PDF 资料",
  poster: "海报",
  card: "名片",
};

const MODULE_HINT: Record<SiteModuleRecord["module_type"], string> = {
  home: "headline / paragraphs[] / links[]",
  services: "items[{ name, desc }]",
  news: "items[{ title, url, date }]",
  download: "items[{ name, url }]",
  poster: "items[{ title, image_url }]",
  card: "name / role / phone / wechat / qrcode_url",
};

/** 每个模块一个 JSON 编辑框：直接看字段结构，不猜「该填什么」。 */
interface ModuleDraft {
  title: string;
  content: string;
  sort_order: number;
  is_active: boolean;
  dirty: boolean;
  error: string;
}

function toDraft(module: SiteModuleRecord): ModuleDraft {
  return {
    title: module.title,
    content: JSON.stringify(module.content ?? {}, null, 2),
    sort_order: module.sort_order,
    is_active: module.is_active,
    dirty: false,
    error: "",
  };
}

export function MicrositeWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; onNotice: (message: string) => void;
}) {
  const [site, setSite] = useState<SiteRecord | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ModuleDraft>>({});
  const [siteForm, setSiteForm] = useState<{ title: string; intro: string; slug: string } | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState("");
  const [loadedFor, setLoadedFor] = useState("");

  const requestKey = `${mode}:${projectId}`;
  const showLoading = mode === "live" && canRead && !!projectId && projectId !== "all" && loadedFor !== requestKey;

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.site(projectId)
      .then((data) => {
        if (!active) return;
        setSite(data);
        setSiteForm({ title: data.title, intro: data.intro ?? "", slug: data.slug });
        setDrafts(Object.fromEntries(data.modules.map((module) => [module.module_type, toDraft(module)])));
        setError("");
        setLoadedFor(requestKey);
      })
      .catch((cause) => {
        if (!active) return;
        setSite(null);
        setError(cause instanceof Error ? cause.message : "微站配置加载失败");
        setLoadedFor(requestKey);
      });
    return () => { active = false; };
  }, [mode, canRead, projectId, requestKey]);

  async function saveSite(nextPublished?: boolean) {
    if (!canWrite || !siteForm) return;
    setSaving("site");
    try {
      const updated = await workbenchClient.updateSite(projectId, {
        title: siteForm.title.trim(),
        intro: siteForm.intro.trim() || null,
        slug: siteForm.slug.trim() || undefined,
        ...(nextPublished === undefined ? {} : { is_published: nextPublished }),
      });
      setSite(updated);
      setSiteForm({ title: updated.title, intro: updated.intro ?? "", slug: updated.slug });
      onNotice(nextPublished === undefined ? "站点信息已保存" : nextPublished ? "微站已发布" : "微站已下线");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setSaving(""); }
  }

  async function saveModule(module: SiteModuleRecord) {
    if (!canWrite) return;
    const draft = drafts[module.module_type];
    if (!draft) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(draft.content);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("内容必须是 JSON 对象");
    } catch (cause) {
      setDrafts((rows) => ({ ...rows, [module.module_type]: { ...draft, error: cause instanceof Error ? cause.message : "JSON 解析失败" } }));
      return;
    }
    setSaving(module.module_type);
    try {
      const updated = await workbenchClient.updateSite(projectId, {
        title: draft.title.trim() || MODULE_LABEL[module.module_type],
        content: parsed,
        sort_order: draft.sort_order,
        is_active: draft.is_active,
      }, module.module_type);
      setSite(updated);
      setDrafts(Object.fromEntries(updated.modules.map((row) => [row.module_type, toDraft(row)])));
      onNotice(`${MODULE_LABEL[module.module_type]}已保存`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setSaving(""); }
  }

  function patchDraft(type: SiteModuleRecord["module_type"], changes: Partial<ModuleDraft>) {
    setDrafts((rows) => ({ ...rows, [type]: { ...rows[type], ...changes, dirty: true, error: "" } }));
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">微站配置仅在真实接口模式可用。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  return <div className="microsite-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div><h3>微站</h3><p>只做 6 个内容模块；未发布时公开链接一律 404，不给「半成品站」留入口。</p></div>
        {site && <Badge tone={site.is_published ? "green" : "slate"}>{site.is_published ? "已发布" : "未发布"}</Badge>}
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {showLoading && <p className="knowledge-empty">正在加载微站配置…</p>}
      {site && siteForm && !showLoading && <>
        <div className="microsite-site">
          <label className="field"><span className="field-label">站点标题</span><input className="text-input" value={siteForm.title} maxLength={120} disabled={!canWrite} onChange={(event) => setSiteForm({ ...siteForm, title: event.target.value })}/></label>
          <label className="field"><span className="field-label">访问路径（/s/…）</span><input className="text-input" value={siteForm.slug} maxLength={64} disabled={!canWrite} onChange={(event) => setSiteForm({ ...siteForm, slug: event.target.value })}/></label>
          <label className="field microsite-intro"><span className="field-label">简介</span><textarea className="text-input knowledge-textarea short" value={siteForm.intro} maxLength={2000} disabled={!canWrite} onChange={(event) => setSiteForm({ ...siteForm, intro: event.target.value })}/></label>
          {canWrite && <div className="knowledge-actions">
            <Button onClick={() => void saveSite()} disabled={saving === "site"}>{saving === "site" ? "保存中…" : "保存站点信息"}</Button>
            {site.is_published
              ? <Button variant="secondary" onClick={() => void saveSite(false)}>下线微站</Button>
              : <Button onClick={() => void saveSite(true)}>发布微站</Button>}
            {site.is_published && <a className="microsite-link" href={`/s/${site.slug}`} target="_blank" rel="noreferrer noopener">打开公开站</a>}
          </div>}
        </div>
        <div className="microsite-grid">
          {site.modules.map((module) => {
            const draft = drafts[module.module_type];
            if (!draft) return null;
            return <div className={`microsite-card${draft.is_active ? "" : " microsite-card-off"}`} key={module.module_type}>
              <div className="microsite-card-head">
                <strong>{MODULE_LABEL[module.module_type]}</strong>
                <label className="microsite-switch">
                  <input type="checkbox" checked={draft.is_active} disabled={!canWrite} onChange={(event) => patchDraft(module.module_type, { is_active: event.target.checked })}/>
                  <span>{draft.is_active ? "启用" : "停用"}</span>
                </label>
              </div>
              <p className="microsite-hint">字段：{MODULE_HINT[module.module_type]}</p>
              <label className="field"><span className="field-label">模块标题</span><input className="text-input" value={draft.title} maxLength={120} disabled={!canWrite} onChange={(event) => patchDraft(module.module_type, { title: event.target.value })}/></label>
              <label className="field"><span className="field-label">排序</span><input type="number" className="text-input" min={0} max={99} value={draft.sort_order} disabled={!canWrite} onChange={(event) => patchDraft(module.module_type, { sort_order: Number(event.target.value) })}/></label>
              <label className="field"><span className="field-label">内容 JSON</span><textarea className="text-input microsite-json" value={draft.content} disabled={!canWrite} onChange={(event) => patchDraft(module.module_type, { content: event.target.value })}/></label>
              {draft.error && <p className="form-error" role="alert">{draft.error}</p>}
              {canWrite && <div className="knowledge-actions">
                <Button onClick={() => void saveModule(module)} disabled={saving === module.module_type || !draft.dirty}>{saving === module.module_type ? "保存中…" : "保存模块"}</Button>
              </div>}
            </div>;
          })}
        </div>
      </>}
    </Panel>
  </div>;
}
