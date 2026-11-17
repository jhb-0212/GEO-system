"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { MemberRecord, UserCandidate } from "@/lib/workbench/types";

const grantableRoles = [["editor", "运营编辑"], ["reviewer", "审核"], ["viewer", "只读"], ["lead_ops", "招生客服"]] as const;
const roleLabels: Record<string, string> = { editor: "运营编辑", reviewer: "审核", viewer: "只读", lead_ops: "招生客服", project_admin: "项目管理员" };
const roleLabel = (code: string | null) => (code ? roleLabels[code] ?? code : "—");

export function MembersWorkspace({ mode, projectId, canManage, onNotice }: {
  mode: "mock" | "live"; projectId: string; canManage: boolean; onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<MemberRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<UserCandidate[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [addRole, setAddRole] = useState<string>("editor");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (mode !== "live" || !canManage || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.members(projectId).then((result) => {
      if (active) { setItems(result.data); setError(""); }
    }).catch((cause) => {
      if (active) { setItems([]); setError(cause instanceof Error ? cause.message : "成员加载失败"); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, canManage, projectId, version]);

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage) return;
    try {
      const rows = await workbenchClient.memberCandidates(projectId, query.trim());
      setCandidates(rows);
      setSelected(rows[0]?.id ?? "");
      if (!rows.length) onNotice("没有匹配的候选用户（可能已是成员或用户名不存在）");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "搜索失败"); }
  }

  async function addMember() {
    if (!canManage || !selected) { onNotice("请先搜索并选择候选用户"); return; }
    setBusy(true);
    try {
      await workbenchClient.addMember(projectId, selected, addRole);
      setCandidates([]);
      setSelected("");
      setQuery("");
      setVersion((value) => value + 1);
      onNotice("成员已加入项目");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "添加失败"); }
    finally { setBusy(false); }
  }

  async function changeRole(member: MemberRecord, roleCode: string) {
    if (!canManage) return;
    try {
      await workbenchClient.changeMemberRole(projectId, member.member_id, roleCode);
      setItems((rows) => rows.map((row) => row.member_id === member.member_id ? { ...row, role_code: roleCode } : row));
      onNotice(`已将 ${member.display_name || member.username} 调整为 ${roleLabel(roleCode)}`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "调整失败"); }
  }

  async function remove(member: MemberRecord) {
    if (!canManage) return;
    try {
      await workbenchClient.removeMember(projectId, member.member_id);
      setItems((rows) => rows.map((row) => row.member_id === member.member_id ? { ...row, is_active: false } : row));
      onNotice(`已停用 ${member.display_name || member.username} 的项目权限`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "停用失败"); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">成员管理仅在真实接口模式显示。</p></Panel>;
  if (!canManage) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">只有项目管理员可以管理成员。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>项目成员</h3><p>共 {items.filter((m) => m.is_active).length} 位有效成员 · 仅可授予运营/审核/只读/招生</p></div></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">
        {items.map((member) => <div className="knowledge-item" key={member.member_id}>
          <span><strong>{member.display_name || member.username || "未知用户"}</strong><small>{member.username}{member.email ? ` · ${member.email}` : ""}</small></span>
          <span className="knowledge-actions">
            {member.is_active ? <Badge tone="green">有效</Badge> : <Badge tone="slate">已停用</Badge>}
            {member.role_code === "project_admin" ? <Badge tone="blue">项目管理员</Badge> : (
              <select className="knowledge-filter" aria-label="调整角色" value={member.role_code ?? ""} disabled={!member.is_active} onChange={(event) => void changeRole(member, event.target.value)}>
                {grantableRoles.map(([code, text]) => <option value={code} key={code}>{text}</option>)}
              </select>
            )}
            {member.is_active && member.role_code !== "project_admin" && <Button variant="secondary" onClick={() => void remove(member)}>停用</Button>}
          </span>
        </div>)}
        {loading && !items.length && <p className="knowledge-empty">正在加载成员…</p>}
        {!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无成员。</p>}
      </div>
    </Panel>
    <Panel className="knowledge-editor-panel">
      <div className="panel-heading"><div><h3>添加成员</h3><p>按用户名 / 邮箱 / 显示名搜索，再授予角色</p></div><Icon name="users" size={18}/></div>
      <form onSubmit={search}>
        <label className="field"><span className="field-label">搜索用户</span><input className="text-input" value={query} maxLength={64} placeholder="输入用户名或邮箱" onChange={(event) => setQuery(event.target.value)}/></label>
        <div className="knowledge-actions"><Button type="submit" variant="secondary">搜索候选</Button></div>
      </form>
      {candidates.length > 0 && <>
        <div className="knowledge-list">
          {candidates.map((candidate) => <button type="button" key={candidate.id} className={`knowledge-item ${selected === candidate.id ? "selected" : ""}`} onClick={() => setSelected(candidate.id)}>
            <span><strong>{candidate.display_name}</strong><small>{candidate.username}{candidate.email ? ` · ${candidate.email}` : ""}</small></span>
            {selected === candidate.id ? <Badge tone="blue">已选</Badge> : <Badge tone="slate">选择</Badge>}
          </button>)}
        </div>
        <label className="field"><span className="field-label">授予角色</span><select className="text-input" value={addRole} onChange={(event) => setAddRole(event.target.value)}>{grantableRoles.map(([code, text]) => <option value={code} key={code}>{text}</option>)}</select></label>
        <div className="knowledge-actions"><Button disabled={busy || !selected} onClick={() => void addMember()}>{busy ? "添加中…" : "加入项目"}</Button></div>
      </>}
    </Panel>
  </div>;
}
