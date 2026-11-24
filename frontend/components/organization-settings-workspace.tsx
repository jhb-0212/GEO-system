"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { OrganizationSettings, OrganizationUsageTrend } from "@/lib/workbench/types";

/**
 * 客户设置：继承开关、配额、客户策略 + 用量/告警。
 *
 * 只给系统管理员：客户边界跨项目，项目管理员不应改客户级默认。
 * 配额留空 = 不限；低于 80% 不告警，80% 起黄色，达到上限红色。
 */

const QUOTA_LABELS: Record<keyof OrganizationSettings["quotas"], string> = {
  projects: "客户项目数",
  members: "客户名册人数",
  project_members: "单项目成员数",
};

function toInput(value: number | null): string {
  return value === null || value === undefined ? "" : String(value);
}

function quotaValue(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : null;
}

export function OrganizationSettingsWorkspace({ mode, projectId, isSystemAdmin, onNotice }: {
  mode: "mock" | "live"; projectId: string; isSystemAdmin: boolean; onNotice: (message: string) => void;
}) {
  const [settings, setSettings] = useState<OrganizationSettings | null>(null);
  const [trend, setTrend] = useState<OrganizationUsageTrend | null>(null);
  const [inherit, setInherit] = useState(false);
  const [quotas, setQuotas] = useState<Record<string, string>>({ projects: "", members: "", project_members: "" });
  const [strategy, setStrategy] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (mode !== "live" || !isSystemAdmin || !projectId || projectId === "all") return;
    let active = true;
    setLoading(true);
    Promise.all([
      workbenchClient.organizationSettings(projectId),
      workbenchClient.organizationUsage(projectId, 30),
    ])
      .then(([current, usage]) => {
        if (!active) return;
        setSettings(current);
        setTrend(usage);
        setInherit(current.inherit_members);
        setQuotas({
          projects: toInput(current.quotas.projects),
          members: toInput(current.quotas.members),
          project_members: toInput(current.quotas.project_members),
        });
        setStrategy(JSON.stringify(current.strategy ?? {}, null, 2));
        setError("");
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "客户设置加载失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, isSystemAdmin, projectId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(strategy || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("客户策略必须是 JSON 对象");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "客户策略不是合法 JSON");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await workbenchClient.saveOrganizationSettings(projectId, {
        inherit_members: inherit,
        quotas: {
          projects: quotaValue(quotas.projects),
          members: quotaValue(quotas.members),
          project_members: quotaValue(quotas.project_members),
        },
        strategy: parsed,
      });
      const [refreshed, usage] = await Promise.all([
        workbenchClient.organizationSettings(projectId),
        workbenchClient.organizationUsage(projectId, 30),
      ]);
      setSettings(refreshed);
      setTrend(usage);
      onNotice("客户设置已保存；继承与配额从下一次操作起生效");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">客户设置仅在真实接口模式可用。</p></Panel>;
  if (!isSystemAdmin) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">客户级设置只对系统管理员开放。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  const peak = Math.max(1, ...(trend?.series ?? []).flatMap((point) => [point.projects, point.members]));

  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel brand-summary-panel">
      <div className="panel-heading">
        <div>
          <h3>{settings?.name ?? "客户设置"}</h3>
          <p>{settings ? `客户编码 ${settings.code} · 策略按「预设 → 客户 → 项目」合并` : "正在加载客户设置…"}</p>
        </div>
        {settings?.alerts.length
          ? <Badge tone={settings.alerts.some((item) => item.level === "exceeded") ? "red" : "amber"}>{settings.alerts.length} 条配额提醒</Badge>
          : <Badge tone="green">配额正常</Badge>}
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && !settings && <p className="knowledge-empty">正在加载…</p>}
      {settings?.alerts.map((item) => <div className="knowledge-item" key={item.key}>
        <span>
          <strong>{QUOTA_LABELS[item.key as keyof OrganizationSettings["quotas"]] ?? item.key}</strong>
          <small>{item.message}</small>
        </span>
        <span className="knowledge-actions">
          <Badge tone={item.level === "exceeded" ? "red" : "amber"}>{item.level === "exceeded" ? "已超限" : "接近上限"}</Badge>
        </span>
      </div>)}
    </Panel>

    <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div><h3>当前用量</h3><p>项目数与名册人数按客户计；项目成员数按当前项目计</p></div>
        <Icon name="pulse" size={18}/>
      </div>
      {settings && <div className="knowledge-list">
        {(Object.keys(QUOTA_LABELS) as (keyof OrganizationSettings["quotas"])[]).map((key) => {
          const used = settings.usage[key] ?? 0;
          const limit = settings.quotas[key];
          const percent = limit === null || limit === 0 ? null : Math.min(100, Math.round((used / limit) * 100));
          return <div className="knowledge-item" key={key}>
            <span>
              <strong>{QUOTA_LABELS[key]}</strong>
              <small>{used} / {limit ?? "不限"}{percent !== null ? ` · ${percent}%` : ""}</small>
            </span>
            <span className="knowledge-actions">
              {percent === null
                ? <Badge tone="slate">不限</Badge>
                : <Badge tone={percent >= 100 ? "red" : percent >= 80 ? "amber" : "green"}>{percent}%</Badge>}
            </span>
          </div>;
        })}
      </div>}
      {trend && <div className="knowledge-list">
        <div className="knowledge-item">
          <span>
            <strong>近 {trend.days} 天累计用量</strong>
            <small>按项目/名册创建时间重算，不是快照；最后一天 {trend.series.at(-1)?.projects ?? 0} 个项目、{trend.series.at(-1)?.members ?? 0} 人</small>
          </span>
        </div>
        <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 56, padding: "6px 0" }}>
          {trend.series.map((point) => <div key={point.date} title={`${point.date} · 项目 ${point.projects} · 名册 ${point.members}`} style={{ flex: 1, display: "flex", flexDirection: "column", gap: 1, justifyContent: "flex-end" }}>
            <div style={{ height: `${Math.max(1, (point.projects / peak) * 26)}px`, background: "#4f7cff", borderRadius: 2 }} />
            <div style={{ height: `${Math.max(1, (point.members / peak) * 26)}px`, background: "#9db4ff", borderRadius: 2 }} />
          </div>)}
        </div>
        <p className="knowledge-footnote"><Badge tone="blue">项目</Badge> 深色 · <Badge tone="slate">名册</Badge> 浅色；峰值刻度 {peak}</p>
      </div>}
    </Panel>

    <Panel className="knowledge-editor-panel">
      <div className="panel-heading">
        <div><h3>编辑客户设置</h3><p>留空 = 不限；客户策略为 JSON 对象，项目策略可再覆盖</p></div>
        <Icon name="blocks" size={18}/>
      </div>
      <form onSubmit={save}>
        <label className="field"><span className="field-label">新建项目继承客户名册</span>
          <select className="text-input" value={inherit ? "on" : "off"} onChange={(event) => setInherit(event.target.value === "on")} disabled={busy}>
            <option value="off">关闭（默认）：新建项目不带名册成员</option>
            <option value="on">开启：名册成员以 viewer 加入新项目，不含 owner</option>
          </select>
        </label>
        {(Object.keys(QUOTA_LABELS) as (keyof OrganizationSettings["quotas"])[]).map((key) => (
          <label className="field" key={key}>
            <span className="field-label">{QUOTA_LABELS[key]}配额</span>
            <input className="text-input" type="number" min={0} value={quotas[key]} disabled={busy}
              placeholder="留空表示不限"
              onChange={(event) => setQuotas((current) => ({ ...current, [key]: event.target.value }))}/>
          </label>
        ))}
        <label className="field"><span className="field-label">客户策略（JSON，覆盖行业预设）</span>
          <textarea className="text-input knowledge-textarea" rows={8} value={strategy} disabled={busy}
            onChange={(event) => setStrategy(event.target.value)} spellCheck={false}/>
        </label>
        <p className="knowledge-footnote">示例：{`{"quality":{"absolute_claims":["客户自定义绝对词"]}}`}；保存后立即对所有项目生效，项目自己的策略仍优先。</p>
        <div className="knowledge-actions">
          <Button type="submit" disabled={busy}>{busy ? "正在保存…" : "保存客户设置"}</Button>
        </div>
      </form>
    </Panel>
  </div>;
}
