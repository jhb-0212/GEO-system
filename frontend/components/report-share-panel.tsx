"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import { formatDateTime } from "@/lib/workbench/format";
import type { ReportShareCreateResult, ReportShareRecord } from "@/lib/workbench/types";

const STATUS_LABEL: Record<ReportShareRecord["status"], string> = {
  active: "有效",
  expired: "已过期",
  revoked: "已吊销",
};

export function ReportSharePanel({
  projectId,
  snapshotId,
  month,
  canShare,
  onNotice,
}: {
  projectId: string;
  snapshotId: string | null;
  month: string | null;
  canShare: boolean;
  onNotice?: (message: string) => void;
}) {
  const [shares, setShares] = useState<ReportShareRecord[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revoking, setRevoking] = useState("");
  const [error, setError] = useState("");
  const [newShare, setNewShare] = useState<ReportShareCreateResult | null>(null);
  const [form, setForm] = useState({
    label: "",
    brand_name: "",
    brand_logo_url: "",
    accent_color: "#2563eb",
    password: "",
    expires_in_days: 30,
    contact_text: "",
    show_leads: false,
  });

  async function load() {
    if (!projectId || projectId === "all") return;
    try {
      setShares(await workbenchClient.reportShares(projectId));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "分享链接加载失败");
    }
  }

  useEffect(() => {
    if (!projectId || projectId === "all") return;
    let active = true;
    workbenchClient.reportShares(projectId)
      .then((rows) => {
        if (!active) return;
        setShares(rows);
        setError("");
      })
      .catch((cause) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "分享链接加载失败");
      });
    return () => { active = false; };
  }, [projectId]);

  async function create() {
    if (!snapshotId || busy) return;
    setBusy(true);
    setError("");
    try {
      const created = await workbenchClient.createReportShare(projectId, {
        snapshot_id: snapshotId,
        label: form.label.trim() || null,
        brand_name: form.brand_name.trim() || null,
        brand_logo_url: form.brand_logo_url.trim() || null,
        accent_color: form.accent_color,
        password: form.password.trim() || null,
        expires_in_days: Number(form.expires_in_days) || 30,
        contact_text: form.contact_text.trim() || null,
        show_leads: form.show_leads,
      });
      setNewShare(created);
      setOpen(false);
      setForm((current) => ({ ...current, password: "" }));
      await load();
      onNotice?.("分享链接已生成，令牌只显示这一次，请立即复制");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "分享链接生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(share: ReportShareRecord) {
    if (revoking) return;
    setRevoking(share.share_id);
    setError("");
    try {
      const updated = await workbenchClient.revokeReportShare(projectId, share.share_id);
      setShares((current) => current.map((item) => item.share_id === updated.share_id ? updated : item));
      onNotice?.("分享链接已吊销，立即失效");
      if (newShare?.share_id === share.share_id) setNewShare(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "吊销失败");
    } finally {
      setRevoking("");
    }
  }

  function shareUrl(token: string) {
    return `${window.location.origin}/share/${token}`;
  }

  async function copyLink(token: string) {
    try {
      await navigator.clipboard.writeText(shareUrl(token));
      onNotice?.("链接已复制");
    } catch {
      onNotice?.("复制失败，请手动选择链接复制");
    }
  }

  const activeCount = shares.filter((item) => item.status === "active").length;

  return <Panel className="knowledge-list-panel report-share-panel">
    <div className="panel-heading">
      <div><h3>客户分享</h3><p>只读客户门户；冻结月报 + 有效期 + 可选密码 + 白标，不暴露后台导航</p></div>
      <div className="toolbar-extra">
        <Badge tone={activeCount ? "green" : "slate"}>{activeCount} 个有效链接</Badge>
        {canShare && snapshotId && <Button icon="external" onClick={() => setOpen((value) => !value)}>{open ? "收起" : "生成分享链接"}</Button>}
      </div>
    </div>
    {!canShare && <p className="knowledge-empty">当前账号没有导出权限，不能生成对外分享链接。</p>}
    {canShare && !snapshotId && <p className="knowledge-empty">请先冻结当前月报；客户分享只基于冻结快照，避免数字随后台变化。</p>}
    {error && <p className="form-error" role="alert">{error}</p>}

    {newShare && <div className="report-share-result">
      <div>
        <strong>新链接已生成{month ? ` · ${month}` : ""}</strong>
        <small>令牌只显示一次。关闭页面后无法再次查看，只能吊销后重新生成。</small>
      </div>
      <code>{shareUrl(newShare.token)}</code>
      <div className="report-share-actions">
        <Button onClick={() => void copyLink(newShare.token)}>复制链接</Button>
        <a className="button button-secondary" href={shareUrl(newShare.token)} target="_blank" rel="noreferrer noopener">打开预览</a>
        <Button variant="secondary" onClick={() => setNewShare(null)}>收起</Button>
      </div>
    </div>}

    {open && canShare && snapshotId && <div className="report-share-form">
      <div className="report-share-form-grid">
        <label>内部备注<input value={form.label} maxLength={120} placeholder="例如：给张总的第一版" onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))} /></label>
        <label>客户显示名<input value={form.brand_name} maxLength={80} placeholder="留空则使用项目名" onChange={(event) => setForm((current) => ({ ...current, brand_name: event.target.value }))} /></label>
        <label>品牌 Logo 地址<input value={form.brand_logo_url} maxLength={500} placeholder="https://…（可留空）" onChange={(event) => setForm((current) => ({ ...current, brand_logo_url: event.target.value }))} /></label>
        <label>报告主色<input type="color" value={form.accent_color} onChange={(event) => setForm((current) => ({ ...current, accent_color: event.target.value }))} /></label>
        <label>访问密码<input type="password" value={form.password} maxLength={72} placeholder="留空则无需密码；至少 6 位" onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} /></label>
        <label>有效天数<input type="number" min={1} max={365} value={form.expires_in_days} onChange={(event) => setForm((current) => ({ ...current, expires_in_days: Number(event.target.value) }))} /></label>
        <label className="report-share-wide">页脚联系说明<input value={form.contact_text} maxLength={200} placeholder="例如：如需解读请联系客户成功团队" onChange={(event) => setForm((current) => ({ ...current, contact_text: event.target.value }))} /></label>
      </div>
      <label className="report-share-check"><input type="checkbox" checked={form.show_leads} onChange={(event) => setForm((current) => ({ ...current, show_leads: event.target.checked }))} />向客户展示线索与转化段（默认关闭；关闭时报告中的线索段会被移除）</label>
      <p className="knowledge-footnote">链接内容固定为当前冻结月报；后续数据变化不会改变客户看到的版本。</p>
      <div className="report-share-actions">
        <Button disabled={busy} onClick={() => void create()}>{busy ? "生成中…" : "确认生成"}</Button>
        <Button variant="secondary" disabled={busy} onClick={() => setOpen(false)}>取消</Button>
      </div>
    </div>}

    <div className="report-share-list">
      {!shares.length && <p className="knowledge-empty">还没有客户分享链接。冻结月报后生成一条，客户即可在浏览器中查看只读报告。</p>}
      {shares.map((item) => <div className={`report-share-row is-${item.status}`} key={item.share_id}>
        <div>
          <strong>{item.month || month || "月报"} · {item.brand_name || "未命名客户"}{item.label ? ` · ${item.label}` : ""}</strong>
          <small>
            {item.status === "active" ? `有效至 ${formatDateTime(item.expires_at)}` : item.status === "expired" ? `已于 ${formatDateTime(item.expires_at)} 过期` : `已吊销${item.revoked_at ? ` · ${formatDateTime(item.revoked_at)}` : ""}`}
            {" · "}访问 {item.view_count} 次{item.last_viewed_at ? ` · 最近 ${formatDateTime(item.last_viewed_at)}` : ""}
            {" · "}{item.password_enabled ? "有密码" : "无密码"}{item.show_leads ? " · 含线索段" : " · 隐藏线索段"}
          </small>
        </div>
        <div className="report-share-actions">
          <Badge tone={item.status === "active" ? "green" : item.status === "expired" ? "amber" : "slate"}>{STATUS_LABEL[item.status]}</Badge>
          {item.status === "active" && canShare && <Button variant="secondary" disabled={revoking === item.share_id} onClick={() => void revoke(item)}>{revoking === item.share_id ? "吊销中…" : "吊销"}</Button>}
        </div>
      </div>)}
    </div>
    <p className="knowledge-footnote">分享令牌只在生成时返回一次；列表只显示状态与访问次数，不回传令牌。</p>
  </Panel>;
}
