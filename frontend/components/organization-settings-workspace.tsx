"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { OrganizationMember, OrganizationSettings, OrganizationSummary, OrganizationUsageTrend, Project } from "@/lib/workbench/types";

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

export function OrganizationSettingsWorkspace({ mode, projectId, isSystemAdmin, projects, onNotice }: {
  mode: "mock" | "live"; projectId: string; isSystemAdmin: boolean; projects: Project[]; onNotice: (message: string) => void;
}) {
  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
  const [newOrg, setNewOrg] = useState({ code: "", name: "" });
  const [newProject, setNewProject] = useState({ code: "", name: "" });
  const [targetOrg, setTargetOrg] = useState("");
  const [orgBusy, setOrgBusy] = useState(false);
  const [orgError, setOrgError] = useState("");
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [memberName, setMemberName] = useState("");
  const [memberBusy, setMemberBusy] = useState(false);
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
      workbenchClient.organizationMembers(projectId),
    ])
      .then(([current, usage, roster]) => {
        if (!active) return;
        setSettings(current);
        setTrend(usage);
        setMembers(roster);
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

  useEffect(() => {
    if (mode !== "live" || !isSystemAdmin) return;
    let active = true;
    workbenchClient.organizations()
      .then((rows) => { if (active) { setOrganizations(rows); setOrgError(""); } })
      .catch((cause) => { if (active) setOrgError(cause instanceof Error ? cause.message : "客户列表加载失败"); });
    return () => { active = false; };
  }, [mode, isSystemAdmin]);

  function openOrganization(org: OrganizationSummary) {
    const first = projects.find((item) => item.organizationId === org.id);
    if (!first) {
      setTargetOrg(org.id);
      onNotice(`「${org.name}」还没有项目，先建一个再进入`);
      return;
    }
    window.location.assign(`/workbench?section=organization&project_id=${first.id}`);
  }

  async function createOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newOrg.code.trim() || !newOrg.name.trim()) { setOrgError("客户编码与名称必填"); return; }
    setOrgBusy(true);
    setOrgError("");
    try {
      const created = await workbenchClient.createOrganization({ code: newOrg.code.trim(), name: newOrg.name.trim() });
      const rows = await workbenchClient.organizations();
      setOrganizations(rows);
      setNewOrg({ code: "", name: "" });
      setTargetOrg(created.id);
      setNewProject({ code: `${created.code}-01`, name: `${created.name} · 首个项目` });
      onNotice(`客户「${created.name}」已创建，接着建第一个项目`);
    } catch (cause) {
      setOrgError(cause instanceof Error ? cause.message : "创建客户失败");
    } finally {
      setOrgBusy(false);
    }
  }

  async function createProjectUnderOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!targetOrg) { setOrgError("请先选择客户"); return; }
    if (!newProject.code.trim() || !newProject.name.trim()) { setOrgError("项目编码与名称必填"); return; }
    setOrgBusy(true);
    setOrgError("");
    try {
      const created = await workbenchClient.createProject({
        code: newProject.code.trim(), name: newProject.name.trim(), organization_id: targetOrg,
      });
      window.location.assign(`/workbench?section=organization&project_id=${created.id}`);
    } catch (cause) {
      setOrgError(cause instanceof Error ? cause.message : "创建项目失败");
      setOrgBusy(false);
    }
  }

  async function refreshMembers() {
    setMembers(await workbenchClient.organizationMembers(projectId));
  }

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!memberName.trim()) return;
    setMemberBusy(true);
    setOrgError("");
    try {
      await workbenchClient.addOrganizationMember(projectId, memberName.trim());
      setMemberName("");
      await refreshMembers();
      onNotice("已加入客户名册；名册本身不授予项目访问权");
    } catch (cause) {
      setOrgError(cause instanceof Error ? cause.message : "加入名册失败");
    } finally {
      setMemberBusy(false);
    }
  }

  async function removeMember(member: OrganizationMember) {
    if (!window.confirm(`把 ${member.username} 移出客户名册？项目里已有的授权不会被自动收回。`)) return;
    setMemberBusy(true);
    try {
      await workbenchClient.removeOrganizationMember(projectId, member.user_id);
      await refreshMembers();
      onNotice("已移出客户名册；项目成员授权保持原样");
    } catch (cause) {
      setOrgError(cause instanceof Error ? cause.message : "移出名册失败");
    } finally {
      setMemberBusy(false);
    }
  }

  async function syncMembers() {
    setMemberBusy(true);
    try {
      const result = await workbenchClient.syncOrganizationMembers(projectId);
      await refreshMembers();
      onNotice(`已同步：新增 ${String(result.created ?? 0)} 名 viewer，已有成员角色不变`);
    } catch (cause) {
      setOrgError(cause instanceof Error ? cause.message : "同步失败");
    } finally {
      setMemberBusy(false);
    }
  }

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
    <Panel className="knowledge-list-panel organization-directory-panel">
      <div className="panel-heading">
        <div><h3>客户与项目</h3><p>客户是项目之上的边界；先建客户，再在该客户下建第一个项目</p></div>
        <Badge tone="blue">{organizations.length} 个客户</Badge>
      </div>
      {orgError && <p className="form-error" role="alert">{orgError}</p>}
      <div className="knowledge-list">
        {organizations.map((org) => {
          const orgProjects = projects.filter((item) => item.organizationId === org.id);
          return <div className="knowledge-item" key={org.id}>
            <span>
              <strong>{org.name}{org.id === settings?.organization_id ? <Badge tone="green">当前</Badge> : null}</strong>
              <small>{org.code} · {org.project_count} 个项目 · 名册 {org.member_count} 人{orgProjects.length ? ` · ${orgProjects.slice(0, 2).map((item) => item.name).join("、")}${orgProjects.length > 2 ? "…" : ""}` : " · 还没有项目"}</small>
            </span>
            <span className="knowledge-actions">
              <Button variant="secondary" icon="arrowRight" disabled={orgBusy} onClick={() => openOrganization(org)}>进入</Button>
              <Button variant="quiet" icon="plus" disabled={orgBusy} onClick={() => {
                setTargetOrg(org.id);
                setNewProject({ code: `${org.code}-02`, name: `${org.name} · 新项目` });
              }}>新建项目</Button>
            </span>
          </div>;
        })}
        {!organizations.length && <p className="knowledge-empty">还没有客户，先在右边建一个。</p>}
      </div>
      <p className="knowledge-footnote">客户下没有项目时「进入」会提示先建项目；名册人数为启用中的客户成员。</p>
    </Panel>

    <Panel className="knowledge-editor-panel">
      <div className="panel-heading">
        <div><h3>新建客户 / 项目</h3><p>客户编码全局唯一；项目编码也全局唯一，建议带客户前缀</p></div>
        <Icon name="plus" size={18}/>
      </div>
      <form onSubmit={createOrganization} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginTop: 12 }}>
        <label className="field" style={{ flex: "1 1 200px" }}><span className="field-label">客户编码</span>
          <input className="text-input" value={newOrg.code} disabled={orgBusy} placeholder="小写字母/数字/短横线，如 acme-gz"
            onChange={(event) => setNewOrg((current) => ({ ...current, code: event.target.value.toLowerCase() }))}/>
        </label>
        <label className="field" style={{ flex: "2 1 280px" }}><span className="field-label">客户名称</span>
          <input className="text-input" value={newOrg.name} disabled={orgBusy} placeholder="对客可见的名称"
            onChange={(event) => setNewOrg((current) => ({ ...current, name: event.target.value }))}/>
        </label>
        <Button type="submit" icon="plus" disabled={orgBusy}>{orgBusy ? "处理中…" : "新建客户"}</Button>
      </form>
      {targetOrg && <form onSubmit={createProjectUnderOrganization} style={{ marginTop: 14, borderTop: "1px solid var(--line, #e6e8ec)", paddingTop: 12 }}>
        <p className="knowledge-footnote">在「{organizations.find((item) => item.id === targetOrg)?.name ?? "所选客户"}」下新建项目（owner 为当前账号，行业留空由开通向导选择）</p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field" style={{ flex: "1 1 200px" }}><span className="field-label">项目编码</span>
            <input className="text-input" value={newProject.code} disabled={orgBusy} placeholder="如 acme-gz-01"
              onChange={(event) => setNewProject((current) => ({ ...current, code: event.target.value.toLowerCase() }))}/>
          </label>
          <label className="field" style={{ flex: "2 1 280px" }}><span className="field-label">项目名称</span>
            <input className="text-input" value={newProject.name} disabled={orgBusy}
              onChange={(event) => setNewProject((current) => ({ ...current, name: event.target.value }))}/>
          </label>
          <Button type="submit" icon="plus" disabled={orgBusy}>创建并进入项目</Button>
          <Button type="button" variant="quiet" disabled={orgBusy} onClick={() => setTargetOrg("")}>取消</Button>
        </div>
      </form>}
    </Panel>

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

    <Panel className="knowledge-list-panel organization-directory-panel">
      <div className="panel-heading">
        <div><h3>客户名册</h3><p>名册是客户通讯录，不授予项目访问权；同步时才以 viewer 加进本项目</p></div>
        <Badge tone="blue">{members.length} 人</Badge>
      </div>
      {orgError && <p className="form-error" role="alert">{orgError}</p>}
      <div className="knowledge-list">
        {members.map((item) => <div className="knowledge-item" key={item.user_id}>
          <span>
            <strong>{item.display_name || item.username}</strong>
            <small>{item.username}{item.is_active ? "" : " · 账号已停用"} · 名册角色 {item.role}</small>
          </span>
          <span className="knowledge-actions">
            {item.in_project ? <Badge tone="green">已在本项目</Badge> : <Badge tone="slate">未进项目</Badge>}
            <Button variant="quiet" disabled={memberBusy} onClick={() => void removeMember(item)}>移出名册</Button>
          </span>
        </div>)}
        {!members.length && <p className="knowledge-empty">名册还是空的；用工作账号加入，或先同步一次。</p>}
      </div>
      <form onSubmit={addMember} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginTop: 12 }}>
        <label className="field" style={{ flex: "1 1 240px" }}><span className="field-label">工作账号</span>
          <input className="text-input" value={memberName} disabled={memberBusy} placeholder="如 geo_viewer"
            onChange={(event) => setMemberName(event.target.value)}/>
        </label>
        <Button type="submit" icon="plus" disabled={memberBusy}>加入名册</Button>
        <Button type="button" variant="secondary" icon="refresh" disabled={memberBusy} onClick={() => void syncMembers()}>同步到本项目</Button>
      </form>
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
