"use client";

import { useCallback, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { TablePager } from "./table-pager";
import { MEMBERS_PAGE_SIZE, workbenchClient } from "@/lib/workbench/client";
import { usePagedData } from "@/lib/workbench/use-paged-data";
import type { MemberRecord, UserCandidate } from "@/lib/workbench/types";

const grantableRoles = [["editor", "运营编辑"], ["reviewer", "审核"], ["viewer", "只读"], ["lead_ops", "招生客服"]] as const;
const roleLabels: Record<string, string> = { editor: "运营编辑", reviewer: "审核", viewer: "只读", lead_ops: "招生客服", project_admin: "项目管理员" };
const roleLabel = (code: string | null) => (code ? roleLabels[code] ?? code : "—");

export function MembersWorkspace({ mode, projectId, canManage, isSystemAdmin, onNotice }: {
  mode: "mock" | "live"; projectId: string; canManage: boolean; isSystemAdmin?: boolean; onNotice: (message: string) => void;
}) {
  const fetchMembers = useCallback((target: number) => workbenchClient.members(projectId, target), [projectId]);
  const { rows, total, page, setPage, setRows, loading, error, refresh } = usePagedData<MemberRecord>({
    fetchPage: fetchMembers,
    enabled: mode === "live" && canManage && !!projectId && projectId !== "all",
  });
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<UserCandidate[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [addRole, setAddRole] = useState<string>("editor");
  const [busy, setBusy] = useState(false);
  const [resetTarget, setResetTarget] = useState<MemberRecord | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [resetError, setResetError] = useState("");

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
      refresh();
      onNotice("成员已加入项目");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "添加失败"); }
    finally { setBusy(false); }
  }

  async function changeRole(member: MemberRecord, roleCode: string) {
    if (!canManage) return;
    try {
      await workbenchClient.changeMemberRole(projectId, member.member_id, roleCode);
      setRows((current) => current.map((row) => row.member_id === member.member_id ? { ...row, role_code: roleCode } : row));
      onNotice(`已将 ${member.display_name || member.username} 调整为 ${roleLabel(roleCode)}`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "调整失败"); }
  }

  async function remove(member: MemberRecord) {
    if (!canManage) return;
    try {
      await workbenchClient.removeMember(projectId, member.member_id);
      setRows((current) => current.map((row) => row.member_id === member.member_id ? { ...row, is_active: false } : row));
      onNotice(`已停用 ${member.display_name || member.username} 的项目权限`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "停用失败"); }
  }

  function openReset(member: MemberRecord) {
    setResetTarget(member);
    setResetPassword("");
    setResetError("");
  }

  async function submitReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resetTarget) return;
    setResetError("");
    if (resetPassword.length < 8) {
      setResetError("新密码至少 8 位");
      return;
    }
    setResetBusy(true);
    try {
      await workbenchClient.resetUserPassword(resetTarget.user_id, resetPassword);
      const label = resetTarget.display_name || resetTarget.username || "该成员";
      setResetTarget(null);
      setResetPassword("");
      onNotice(`已重置 ${label} 的密码，该账号在所有设备上的登录已失效`);
    } catch (cause) {
      setResetError(cause instanceof Error ? cause.message : "重置失败，请稍后再试");
    } finally {
      setResetBusy(false);
    }
  }

  function goToPage(next: number) {
    setPage(next);
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">成员管理仅在真实接口模式显示。</p></Panel>;
  if (!canManage) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">只有项目管理员可以管理成员。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>项目成员</h3><p>共 {total} 位成员 · 本页 {rows.filter((m) => m.is_active).length} 位有效成员 · 仅可授予运营/审核/只读/招生</p></div></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">
        {rows.map((member) => <div className="knowledge-item" key={member.member_id}>
          <span><strong>{member.display_name || member.username || "未知用户"}</strong><small>{member.username}{member.email ? ` · ${member.email}` : ""}</small></span>
          <span className="knowledge-actions">
            {member.is_active ? <Badge tone="green">有效</Badge> : <Badge tone="slate">已停用</Badge>}
            {member.role_code === "project_admin" ? <Badge tone="blue">项目管理员</Badge> : (
              <select className="knowledge-filter" aria-label="调整角色" value={member.role_code ?? ""} disabled={!member.is_active} onChange={(event) => void changeRole(member, event.target.value)}>
                {grantableRoles.map(([code, text]) => <option value={code} key={code}>{text}</option>)}
              </select>
            )}
            {member.is_active && member.role_code !== "project_admin" && <Button variant="secondary" onClick={() => void remove(member)}>停用</Button>}
            {isSystemAdmin && member.is_active && <Button variant="secondary" onClick={() => openReset(member)}>重置密码</Button>}
          </span>
        </div>)}
        {loading && !rows.length && <p className="knowledge-empty">正在加载成员…</p>}
        {!loading && !rows.length && !error && <p className="knowledge-empty">当前项目暂无成员。</p>}
      </div>
      <TablePager page={page} total={total} pageSize={MEMBERS_PAGE_SIZE} loading={loading} onChange={goToPage}/>
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
    {resetTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !resetBusy) setResetTarget(null); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="reset-password-title"><div className="modal-header"><div><p className="eyebrow">RESET PASSWORD</p><h2 id="reset-password-title">重置密码</h2></div><button className="icon-button" aria-label="关闭" disabled={resetBusy} onClick={() => setResetTarget(null)}><Icon name="close" size={19}/></button></div><p className="modal-description">为 {resetTarget.display_name || resetTarget.username || "该成员"} 设置新密码。保存后该账号在所有设备上的登录都会失效，需要用它重新登录。</p><form onSubmit={submitReset}><label className="field"><span className="field-label">新密码 *</span><input className="text-input" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={resetPassword} placeholder="至少 8 位" onChange={(event) => setResetPassword(event.target.value)}/></label>{resetError && <p className="form-error" role="alert">{resetError}</p>}<div className="modal-actions"><Button type="button" variant="secondary" disabled={resetBusy} onClick={() => setResetTarget(null)}>取消</Button><Button type="submit" disabled={resetBusy}>{resetBusy ? "提交中…" : "确认重置"}</Button></div></form></div></div>}
  </div>;
}
