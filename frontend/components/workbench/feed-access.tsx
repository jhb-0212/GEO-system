"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Icon, Panel } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { OAuthConnectionRecord, StartupMaterialsRecord, StartupMaterialItemRecord } from "@/lib/workbench/types";

/**
 * K2 投喂 / K10 授权（只读页）。
 *
 * 只回答两件事：投喂材料齐不齐（后端算好的盘点，缺口显式列出）、
 * 对外授权有哪些（OAuth 已连接账号 + 授权案例素材）。
 * 这里不做任何写入，也不把「有记录」读成「可发布」——判定口径由后端给。
 */

const STATUS_LABEL: Record<StartupMaterialItemRecord["status"], string> = {
  ready: "已具备",
  partial: "部分可用",
  missing: "缺失",
};

const STATUS_TONE: Record<StartupMaterialItemRecord["status"], "green" | "amber" | "red"> = {
  ready: "green",
  partial: "amber",
  missing: "red",
};

const CONNECTION_STATUS: Record<string, { label: string; tone: "green" | "amber" | "red" | "slate" }> = {
  connected: { label: "已授权", tone: "green" },
  revoked: { label: "已撤销", tone: "slate" },
  error: { label: "异常", tone: "red" },
};

function connectionTone(status: string): "green" | "amber" | "red" | "slate" {
  return CONNECTION_STATUS[status]?.tone ?? "amber";
}

function connectionLabel(status: string): string {
  return CONNECTION_STATUS[status]?.label ?? status;
}

export function FeedAccessWorkspace({
  mode,
  projectId,
  canRead,
  canReadPublish,
  onNavigate,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canReadPublish: boolean;
  onNavigate?: (section: "brand" | "materials" | "publishing" | "company") => void;
}) {
  const [materials, setMaterials] = useState<StartupMaterialsRecord | null>(null);
  const [connections, setConnections] = useState<OAuthConnectionRecord[] | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const loading = active && loadedFor !== projectId;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    workbenchClient.startupMaterials(projectId)
      .then((record) => { if (!cancelled) setMaterials(record); })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "投喂盘点加载失败"); })
      .finally(() => { if (!cancelled) setLoadedFor(projectId); });
    if (canReadPublish) {
      workbenchClient.oauthConnections(projectId)
        .then((rows) => { if (!cancelled) setConnections(rows); })
        .catch(() => { if (!cancelled) setConnections(null); });
    }
    return () => { cancelled = true; };
  }, [projectId, active, canReadPublish]);

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不展示投喂盘点" description="投喂就绪度依赖真实素材、FAQ 与授权案例，演示数据不参与判定。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看投喂盘点" description="当前账号缺少项目读取能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="投喂材料按项目盘点；在右上角选择具体项目后查看。" />;
  }
  if (loading) {
    return <StatePlaceholder kind="loading" title="正在盘点投喂材料" />;
  }
  if (error) {
    return <StatePlaceholder kind="error" title="投喂盘点加载失败" description={error} />;
  }

  const items = materials?.items ?? [];
  const missing = materials?.missing ?? [];
  const readyCount = items.filter((item) => item.status === "ready").length;
  const activeConnections = (connections ?? []).filter((row) => row.status === "connected");

  return (
    <div className="feed-layout">
      <div className="feed-main">
        <Panel className="company-panel" title="投喂材料就绪度">
          <div className="panel-heading">
            <div>
              <h3>投喂材料就绪度</h3>
              <p>6 项材料逐项判定，缺口直接列出来；这里不合成总分，也不把空值当成已具备</p>
            </div>
            <Badge tone={missing.length ? "amber" : "green"}>{missing.length ? `${missing.length} 项待补` : "全部就绪"}</Badge>
          </div>
          <div className="feed-items">
            {items.map((item) => (
              <div className="feed-item" key={item.key}>
                <div className="feed-item-head">
                  <strong>{item.label}</strong>
                  <Badge tone={STATUS_TONE[item.status]}>{STATUS_LABEL[item.status]}</Badge>
                </div>
                <p className="feed-item-detail">{item.detail}</p>
                <span className="feed-item-count">计数 {item.count}</span>
              </div>
            ))}
          </div>
          {missing.length > 0 && (
            <div className="feed-missing">
              <span className="feed-missing-title">待补清单</span>
              <ul>
                {missing.map((row) => <li key={row}><Icon name="info" size={13} />{row}</li>)}
              </ul>
            </div>
          )}
        </Panel>

        <Panel className="company-panel" title="投喂去向">
          <div className="panel-heading"><div><h3>投喂去向</h3><p>材料齐了之后，下一步是把口径推到各 AI 平台的入口</p></div></div>
          {readyCount === items.length && items.length > 0 ? (
            <p className="feed-note">材料已全部就绪，可以进入批量生成与投喂环节。</p>
          ) : (
            <p className="feed-note">还有 {items.length - readyCount} 项材料未就绪。先补齐再投喂，否则推出去的口径不一致，后面还得回改。</p>
          )}
          <p className="feed-note-muted">投喂执行（批次、预检、抽样审核）属于内容工厂阶段，当前未开建；本页只做就绪度判定。</p>
        </Panel>
      </div>

      <aside className="company-side">
        <div className="company-side-card">
          <div className="g-tile-head"><span className="g-tile-label">平台授权账号</span><Badge tone={activeConnections.length ? "green" : "slate"}>{activeConnections.length} 个有效</Badge></div>
          {!canReadPublish ? (
            <p className="company-side-note">当前账号缺少 publish.read 能力，看不到授权账号清单。</p>
          ) : connections === null ? (
            <p className="company-side-note">授权账号加载失败，稍后刷新重试。</p>
          ) : connections.length === 0 ? (
            <p className="company-side-note">还没有任何平台授权。到「内容发布 → 平台授权」发起授权后，这里会列出账号与令牌状态。</p>
          ) : (
            <ul className="feed-connections">
              {connections.map((row) => (
                <li key={row.id}>
                  <div className="feed-connection-head">
                    <strong>{row.external_account_name || row.external_account_id}</strong>
                    <Badge tone={connectionTone(row.status)}>{connectionLabel(row.status)}</Badge>
                  </div>
                  <small>{row.provider_name}{row.external_account_email ? ` · ${row.external_account_email}` : ""}</small>
                  <small className="feed-connection-meta">
                    令牌刷新 {row.has_refresh_token ? "可续期" : "不含 refresh token"}
                    {row.expires_at ? ` · 到期 ${row.expires_at}` : ""}
                  </small>
                </li>
              ))}
            </ul>
          )}
          {onNavigate && canReadPublish && (
            <Button variant="quiet" icon="arrowRight" onClick={() => onNavigate("publishing")}>去内容发布</Button>
          )}
        </div>

        <div className="company-side-card">
          <div className="g-tile-head"><span className="g-tile-label">授权凭证与案例</span></div>
          <p className="company-side-note">
            授权作品/脱敏案例的素材数量已计入上面的「授权作品/脱敏案例」一项。案例素材统一放「素材管理」的案例分组，避免同一份图两处存放。
          </p>
          {onNavigate && <Button variant="quiet" icon="arrowRight" onClick={() => onNavigate("materials")}>去素材管理</Button>}
        </div>

        <div className="company-side-card">
          <div className="g-tile-head"><span className="g-tile-label">判定口径</span></div>
          <p className="company-side-note">
            每项状态由后端按真实库字段现算：测试账号、空凭据、草稿 FAQ 一律不算「已具备」。缺项只提示，不阻塞保存。
          </p>
        </div>
      </aside>
    </div>
  );
}
