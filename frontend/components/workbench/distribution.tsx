"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Panel, TextInput } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { ContentVersionRecord, DistributionBatchRecord, EngineRecord } from "@/lib/workbench/types";

/**
 * G9 投喂批次。
 *
 * 创建即预检：五项任一不过就是 blocked，页面不给「标记已投喂」按钮。
 * 页面只展示后端给的 checks，不再自己判断一遍，避免两套口径。
 */

const STATUS_LABEL: Record<DistributionBatchRecord["status"], string> = {
  blocked: "预检未过",
  ready: "可以投喂",
  dispatched: "已投喂",
};

const STATUS_TONE: Record<DistributionBatchRecord["status"], "red" | "green" | "blue"> = {
  blocked: "red",
  ready: "green",
  dispatched: "blue",
};

export function DistributionWorkspace({
  mode,
  projectId,
  canRead,
  canWrite,
  onNotice,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canWrite: boolean;
  onNotice: (message: string) => void;
}) {
  const [batches, setBatches] = useState<DistributionBatchRecord[]>([]);
  const [versions, setVersions] = useState<ContentVersionRecord[]>([]);
  const [engines, setEngines] = useState<EngineRecord[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [versionIds, setVersionIds] = useState<string[]>([]);
  const [engineIds, setEngineIds] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const loading = active && loadedFor !== projectId;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    Promise.all([
      workbenchClient.distributionBatches(projectId),
      workbenchClient.contentVersions(projectId, "approved"),
      workbenchClient.engines(),
    ])
      .then(([list, approved, enginePage]) => {
        if (cancelled) return;
        setBatches(list.data);
        setVersions(approved.data);
        setEngines((enginePage.data ?? []).filter((engine) => engine.is_active));
        setError("");
      })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "批次加载失败"); })
      .finally(() => { if (!cancelled) setLoadedFor(projectId); });
    return () => { cancelled = true; };
  }, [projectId, active]);

  async function create() {
    if (!canWrite) return;
    if (!name.trim()) { onNotice("给批次起个名字"); return; }
    if (!versionIds.length) { onNotice("至少选一个已审核版本"); return; }
    if (!engineIds.length) { onNotice("至少选一个目标平台"); return; }
    setSaving(true);
    try {
      const created = await workbenchClient.createDistributionBatch(projectId, {
        name: name.trim(),
        content_version_ids: versionIds,
        engine_ids: engineIds,
        notes: notes.trim() || null,
      });
      setBatches((current) => [created, ...current]);
      setName("");
      setVersionIds([]);
      setEngineIds([]);
      setNotes("");
      onNotice(created.status === "ready" ? "批次已建好，预检全部通过" : "批次已建好，但预检未通过，按缺口补齐后重检");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "批次创建失败");
    } finally {
      setSaving(false);
    }
  }

  async function act(batch: DistributionBatchRecord, action: "recheck" | "dispatch") {
    if (!canWrite) return;
    try {
      const updated = await workbenchClient.distributionBatchAction(projectId, batch.id, action);
      setBatches((current) => current.map((row) => row.id === updated.id ? updated : row));
      onNotice(action === "recheck" ? `已重检：${STATUS_LABEL[updated.status]}` : "已标记投喂完成");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "操作失败");
    }
  }

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不展示投喂批次" description="批次预检依赖真实档案、内容与问答，演示数据不参与。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看投喂批次" description="当前账号缺少内容读取能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="投喂批次按项目计算；在右上角选择具体项目后查看。" />;
  }
  if (loading) return <StatePlaceholder kind="loading" title="正在加载投喂批次" />;
  if (error) return <StatePlaceholder kind="error" title="批次加载失败" description={error} />;

  return (
    <div className="report-layout">
      {canWrite && (
        <Panel title="新建投喂批次">
          <div className="dist-form">
            <TextInput label="批次名称 *" value={name} maxLength={120} placeholder="例如：12 月首批口径投喂" onChange={(event) => setName(event.target.value)} />
            <div className="dist-block">
              <span className="field-label">已审核内容版本（可多选）</span>
              {versions.length === 0 ? (
                <p className="dist-hint">没有已审核版本。先把内容审核通过再来建批次。</p>
              ) : (
                <div className="dist-chips">
                  {versions.map((version) => (
                    <button
                      type="button"
                      key={version.version_id}
                      className={`basic-cat-chip${versionIds.includes(version.version_id) ? " active" : ""}`}
                      onClick={() => setVersionIds((current) => current.includes(version.version_id) ? current.filter((id) => id !== version.version_id) : [...current, version.version_id])}
                    >
                      {version.title} · v{version.version_no}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="dist-block">
              <span className="field-label">目标平台（可多选）</span>
              {engines.length === 0 ? (
                <p className="dist-hint">没有启用中的引擎。</p>
              ) : (
                <div className="dist-chips">
                  {engines.map((engine) => (
                    <button
                      type="button"
                      key={engine.id}
                      className={`basic-cat-chip${engineIds.includes(engine.id) ? " active" : ""}`}
                      onClick={() => setEngineIds((current) => current.includes(engine.id) ? current.filter((id) => id !== engine.id) : [...current, engine.id])}
                    >
                      {engine.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <label className="field"><span className="field-label">备注</span><textarea className="text-input" rows={2} maxLength={2000} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
            <div className="basic-actions"><Button disabled={saving} onClick={() => void create()}>{saving ? "预检中…" : "创建并预检"}</Button></div>
          </div>
        </Panel>
      )}

      {batches.length === 0 ? (
        <StatePlaceholder kind="empty" compact title="还没有投喂批次" description="选一批已审核内容指向目标平台，系统会先跑五项预检。" />
      ) : (
        <div className="dist-list">
          {batches.map((batch) => (
            <Panel className="dist-card" key={batch.id}>
              <div className="dist-card-head">
                <div>
                  <strong>{batch.name}</strong>
                  <p className="dist-hint">{batch.item_count} 个版本 · {batch.engine_names.join(" / ") || "未选平台"}{batch.last_checked_at ? ` · 重检于 ${batch.last_checked_at.slice(0, 16).replace("T", " ")}` : ""}</p>
                </div>
                <Badge tone={STATUS_TONE[batch.status]}>{STATUS_LABEL[batch.status]}</Badge>
              </div>
              {batch.precheck && (
                <ul className="dist-checks">
                  {batch.precheck.checks.map((check) => (
                    <li key={check.key}>
                      <span className={check.ok ? "dist-check-ok" : "dist-check-fail"}>{check.ok ? "通过" : "未过"}</span>
                      <span className="dist-check-label">{check.label}</span>
                      <span className="dist-check-detail">{check.detail}</span>
                    </li>
                  ))}
                </ul>
              )}
              {canWrite && (
                <div className="basic-actions">
                  <Button variant="quiet" onClick={() => void act(batch, "recheck")}>重新预检</Button>
                  <Button variant="quiet" disabled={batch.status !== "ready"} onClick={() => void act(batch, "dispatch")}>标记已投喂</Button>
                </div>
              )}
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
