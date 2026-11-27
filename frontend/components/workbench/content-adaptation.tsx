"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Panel, SelectInput, TextInput } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelDerivationRecord, ChannelRecord, ContentVersionRecord, MasterDerivationList } from "@/lib/workbench/types";

/**
 * G10/G11 渠道改编与跟版。
 *
 * 能改编的只有「母稿且已过审」的版本——这一条由后端把关，页面只是把选项收窄；
 * 渠道约束只展示客观可判的两项（篇幅、外链），需要配图/来源的写明是人工项，不冒充通过。
 * 母稿改了而渠道稿没跟，就标「未跟版」，不自动改稿也不自动盖状态。
 */

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  pending_review: "待审核",
  approved: "已通过",
  published: "已发布",
  needs_attention: "需关注",
};

/** 与后端 DeriveIn.channel_ids 上限保持一致，避免多选后被一句“参数校验失败”拦掉。 */
const MAX_DERIVE_CHANNELS = 100;

export function ContentAdaptationWorkspace({
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
  const [masters, setMasters] = useState<ContentVersionRecord[]>([]);
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [masterId, setMasterId] = useState("");
  const [detail, setDetail] = useState<{ masterId: string; data: MasterDerivationList } | null>(null);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [titleSuffix, setTitleSuffix] = useState("");
  const [saving, setSaving] = useState(false);
  const [staleList, setStaleList] = useState<ChannelDerivationRecord[]>([]);

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const loading = active && loadedFor !== projectId;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    Promise.all([
      workbenchClient.contentVersions(projectId, "approved"),
      workbenchClient.channels(projectId, 1, 100),
      workbenchClient.consistencyDerivations(projectId, true),
    ])
      .then(([versions, channelPage, stale]) => {
        if (cancelled) return;
        const approvedMasters = versions.data.filter((version) => version.kind === "master");
        setMasters(approvedMasters);
        setChannels((channelPage.data ?? []).filter((channel) => channel.is_active !== false));
        setStaleList(stale.data);
        setMasterId((current) => current || approvedMasters[0]?.item_id || "");
        setError("");
      })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "改编数据加载失败"); })
      .finally(() => { if (!cancelled) setLoadedFor(projectId); });
    return () => { cancelled = true; };
  }, [projectId, active]);

  useEffect(() => {
    // 不在这里同步清空 detail：effect 内 setState 会被 lint 拦，且切母稿时旧数据一闪而过。
    // 改为把「这份血缘属于哪篇母稿」一起存下来，渲染时按 masterId 匹配，不匹配就当没有。
    if (!active || !masterId) return;
    let cancelled = false;
    workbenchClient.contentDerivations(projectId, masterId)
      .then((data) => { if (!cancelled) { setDetail({ masterId, data }); setError(""); } })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "血缘加载失败"); });
    return () => { cancelled = true; };
  }, [projectId, active, masterId]);

  async function derive() {
    if (!canWrite || !masterId) return;
    if (!selectedChannels.length) { onNotice("至少选一个目标渠道"); return; }
    setSaving(true);
    try {
      const result = await workbenchClient.deriveToChannels(projectId, masterId, selectedChannels, titleSuffix.trim() || null);
      setSelectedChannels([]);
      setTitleSuffix("");
      const refreshed = await workbenchClient.contentDerivations(projectId, masterId);
      setDetail({ masterId, data: refreshed });
      const stale = await workbenchClient.consistencyDerivations(projectId, true);
      setStaleList(stale.data);
      onNotice(`已派生 ${result.created.length} 篇渠道稿，均为草稿，需各自走审核`);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "派生失败");
    } finally {
      setSaving(false);
    }
  }

  async function sync(row: ChannelDerivationRecord) {
    if (!canWrite || !masterId) return;
    try {
      const updated = await workbenchClient.syncDerivation(projectId, masterId, row.id);
      setDetail((current) => current && current.masterId === masterId ? {
        masterId,
        data: {
          ...current.data,
          derivations: current.data.derivations.map((item) => item.id === updated.id ? updated : item),
          stale_count: current.data.stale_count - (row.stale ? 1 : 0),
        },
      } : current);
      const stale = await workbenchClient.consistencyDerivations(projectId, true);
      setStaleList(stale.data);
      onNotice("已跟版：渠道稿出了新版本并回到草稿，需要重新审核");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "跟版失败");
    }
  }

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不展示渠道改编" description="改编依赖真实母稿与渠道，演示数据不参与。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看渠道改编" description="当前账号缺少内容读取能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="改编按项目算；在右上角选择具体项目后再用。" />;
  }
  if (loading) return <StatePlaceholder kind="loading" title="正在加载母稿与渠道" />;
  if (error) return <StatePlaceholder kind="error" title="加载失败" description={error} />;

  const shown = detail && detail.masterId === masterId ? detail.data : null;

  return (
    <div className="report-layout">
      <Panel title={canWrite ? "改编母稿到渠道" : "查看母稿改编情况"}>
        {masters.length === 0 ? (
          <p className="factory-hint">还没有「已审核通过」的母稿。母稿未过审不能往渠道上复制。</p>
        ) : (
          <div className="factory-form">
            {/* 母稿选择对只读者也开放：否则只读账号永远只能看到默认那篇的血缘，没法核对别的母稿。 */}
            <SelectInput label="选择母稿（仅已审核通过）" value={masterId} onChange={(event) => setMasterId(event.target.value)}>
              {masters.map((version) => <option key={version.version_id} value={version.item_id}>{version.title} · v{version.version_no}</option>)}
            </SelectInput>
            {canWrite ? (
              <>
                <div className="dist-block">
                  <span className="field-label">目标渠道（可多选）<small className="dist-selected-count">已选 {selectedChannels.length} 个</small></span>
                  {channels.length === 0 ? (
                    <p className="factory-hint">渠道台账里还没有启用中的渠道。</p>
                  ) : (
                    <div className="dist-chips">
                      {channels.map((channel) => (
                        <button
                          type="button"
                          key={channel.id}
                          aria-pressed={selectedChannels.includes(channel.id)}
                          className={`basic-cat-chip${selectedChannels.includes(channel.id) ? " active" : ""}`}
                          onClick={() => setSelectedChannels((current) => {
                            if (current.includes(channel.id)) return current.filter((id) => id !== channel.id);
                            if (current.length >= MAX_DERIVE_CHANNELS) {
                              onNotice(`一次最多派生 ${MAX_DERIVE_CHANNELS} 个渠道，请分批处理`);
                              return current;
                            }
                            return [...current, channel.id];
                          })}
                        >
                          {channel.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <TextInput label="标题后缀（可选）" value={titleSuffix} maxLength={60} placeholder="例如：番禺校区" onChange={(event) => setTitleSuffix(event.target.value)} />
                <div className="basic-actions"><Button disabled={saving || selectedChannels.length === 0} onClick={() => void derive()}>{saving ? "派生中…" : `派生渠道稿${selectedChannels.length ? `（${selectedChannels.length} 个）` : ""}`}</Button></div>
              </>
            ) : (
              <p className="factory-hint">当前账号没有内容写入权限，只能核对血缘与检查结论。</p>
            )}
          </div>
        )}
      </Panel>

      {shown ? (
        <Panel title={`母稿血缘 · ${shown.master_title}`}>
          <p className="factory-hint">
            当前母稿 v{shown.master_version_no}（{STATUS_LABEL[shown.master_version_status] ?? shown.master_version_status}）· hash {shown.master_hash.slice(0, 10)} · 未跟版 {shown.stale_count} 篇
          </p>
          {shown.derivations.length === 0 ? (
            <StatePlaceholder kind="empty" compact title="这篇母稿还没有渠道稿" description="选几个渠道派生出去，每篇都会单独走审核。" />
          ) : (
            <div className="dist-list">
              {shown.derivations.map((row) => (
                <div className="adapt-card" key={row.id}>
                  <div className="dist-card-head">
                    <div>
                      <strong>{row.channel_name} · {row.channel_item_title}</strong>
                      <p className="factory-hint">
                        {row.channel_category_label} · 渠道稿 {STATUS_LABEL[row.item_status ?? ""] ?? row.item_status} · 版本 {STATUS_LABEL[row.version_status ?? ""] ?? row.version_status}
                        {row.synced_at ? ` · 跟版于 ${row.synced_at.slice(0, 16).replace("T", " ")}` : ""}
                      </p>
                    </div>
                    <Badge tone={row.stale ? "red" : "green"}>{row.stale ? "未跟版" : "已同步"}</Badge>
                  </div>
                  <ul className="dist-checks">
                    {row.checks.map((check) => (
                      <li key={check.key}>
                        <span className={check.ok ? "dist-check-ok" : "dist-check-fail"}>{check.ok ? "通过" : "需处理"}</span>
                        <span className="dist-check-label">{check.label}</span>
                        <span className="dist-check-detail">{check.detail}</span>
                      </li>
                    ))}
                  </ul>
                  {canWrite && (
                    <div className="basic-actions">
                      <Button variant="quiet" disabled={!row.stale} onClick={() => void sync(row)}>拉取母稿最新版</Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Panel>
      ) : null}

      <Panel title={`未跟版清单（${staleList.length}）`}>
        {staleList.length === 0 ? (
          <p className="factory-hint">所有渠道稿都与母稿一致。</p>
        ) : (
          <ul className="dist-checks">
            {staleList.map((row) => (
              <li key={row.id}>
                <span className="dist-check-fail">未跟版</span>
                <span className="dist-check-label">{row.master_item_title} → {row.channel_name}</span>
                <span className="dist-check-detail">母稿已到 v{row.master_version_no}，渠道稿仍基于旧版本</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
