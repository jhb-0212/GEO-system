"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Badge, Button, Icon, Panel, SelectInput, TextInput } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { CertificationRecord, MyProfileRecord, ProjectContactRecord, Tone } from "@/lib/workbench/types";

interface Props {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canWrite: boolean;
  onNotice: (message: string) => void;
}

type Tab = "contacts" | "ways" | "certifications" | "encyclopedia";

/** 渠道预设：与后端 CHANNEL_LABELS 一致；后端是唯一判定方，这里只负责选择。 */
const CHANNEL_OPTIONS = [
  { value: "phone", label: "联系电话" },
  { value: "hotline", label: "售后热线" },
  { value: "email", label: "邮箱" },
  { value: "wechat", label: "微信" },
  { value: "wechat_official", label: "微信公众号" },
  { value: "xiaohongshu", label: "小红书" },
  { value: "douyin", label: "抖音" },
  { value: "video_account", label: "视频号" },
  { value: "website", label: "官网" },
  { value: "address", label: "地址" },
  { value: "other", label: "其他" },
] as const;

/** 资质类别预设：只做输入建议，不限制自由填写。 */
const CERT_CATEGORY_PRESETS = ["证照", "办学许可", "行业认证", "荣誉资质", "培训资质"];

interface CertForm {
  id?: string;
  name: string;
  category: string;
  issuer: string;
  cert_no: string;
  issued_on: string;
  expires_on: string;
  evidence_url: string;
  notes: string;
  is_active: boolean;
}

const EMPTY_CERT: CertForm = {
  name: "", category: "", issuer: "", cert_no: "", issued_on: "", expires_on: "",
  evidence_url: "", notes: "", is_active: true,
};

const STATUS_META: Record<string, { label: string; tone: Tone }> = {
  valid: { label: "有效", tone: "green" },
  expiring: { label: "即将到期", tone: "amber" },
  expired: { label: "已过期", tone: "red" },
};

function certStatus(row: Pick<CertificationRecord, "status" | "days_left">): { label: string; tone: Tone } {
  if (!row.status) return { label: "长期有效", tone: "slate" };
  const meta = STATUS_META[row.status] ?? { label: row.status, tone: "slate" as Tone };
  if (row.status === "expiring" && row.days_left !== null) return { label: `剩 ${row.days_left} 天`, tone: meta.tone };
  if (row.status === "expired" && row.days_left !== null) return { label: `逾期 ${Math.abs(row.days_left)} 天`, tone: meta.tone };
  return meta;
}

export function BasicInfoWorkspace({ mode, projectId, canRead, canWrite, onNotice }: Props) {
  const [tab, setTab] = useState<Tab>("contacts");

  if (!canRead) {
    return <StatePlaceholder kind="permission" title="当前账号没有基础信息查看权限" description="联系项目管理员开通「内容读取」后即可查看。" />;
  }
  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不含真实基础信息" description="基础信息直接读写账号与项目库，演示模式下不展示，避免看到与真实账号不一致的示例。" />;
  }

  return (
    <div className="basic-workspace">
      <div className="basic-tabs" role="tablist" aria-label="基础信息分区">
        <button type="button" role="tab" aria-selected={tab === "contacts"} className={tab === "contacts" ? "active" : ""} onClick={() => setTab("contacts")}><Icon name="user" size={15}/>联系人信息</button>
        <button type="button" role="tab" aria-selected={tab === "ways"} className={tab === "ways" ? "active" : ""} onClick={() => setTab("ways")}><Icon name="layers" size={15}/>对外渠道</button>
        <button type="button" role="tab" aria-selected={tab === "certifications"} className={tab === "certifications" ? "active" : ""} onClick={() => setTab("certifications")}><Icon name="check" size={15}/>资质证书</button>
        <button type="button" role="tab" aria-selected={tab === "encyclopedia"} className={tab === "encyclopedia" ? "active" : ""} onClick={() => setTab("encyclopedia")}><Icon name="info" size={15}/>百科词条</button>
      </div>

      {tab === "contacts" && <ContactsTab canWrite={canWrite} onNotice={onNotice} />}
      {tab === "ways" && <WaysTab projectId={projectId} canWrite={canWrite} onNotice={onNotice} />}
      {tab === "certifications" && <CertificationsTab projectId={projectId} canWrite={canWrite} onNotice={onNotice} />}
      {tab === "encyclopedia" && (
        <Panel title="百科词条">
          <StatePlaceholder
            kind="not-collected"
            title="百科词条尚未接入"
            description={(
              <>
                这一块对应第三方百科（百度百科 / 搜狗百科）的词条维护。当前系统只做「官网页面 + FAQ」两类自有阵地，
                百科词条需要独立的编辑与发布流程，暂未开建——不做半成品入口，避免误以为能一键提交。
              </>
            )}
          />
        </Panel>
      )}
    </div>
  );
}

function ContactsTab({ canWrite, onNotice }: { canWrite: boolean; onNotice: (message: string) => void }) {
  const [profile, setProfile] = useState<MyProfileRecord | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ display_name: "", job_title: "", phone: "", wechat: "" });
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    workbenchClient.myProfile()
      .then((record) => {
        if (!active) return;
        setProfile(record);
        setForm({
          display_name: record.display_name ?? "",
          job_title: record.job_title ?? "",
          phone: record.phone ?? "",
          wechat: record.wechat ?? "",
        });
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "资料加载失败"); })
      .finally(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, []);

  function update(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
    setDirty(true);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite) return;
    if (!form.display_name.trim()) { onNotice("姓名不能为空"); return; }
    setSaving(true);
    try {
      const updated = await workbenchClient.saveMyProfile({
        display_name: form.display_name.trim(),
        job_title: form.job_title.trim() || null,
        phone: form.phone.trim() || null,
        wechat: form.wechat.trim() || null,
      });
      setProfile(updated);
      setDirty(false);
      onNotice("联系人信息已保存");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) return <Panel title="联系人信息"><StatePlaceholder kind="loading" compact title="正在读取账号资料" /></Panel>;
  if (error) return <Panel title="联系人信息"><StatePlaceholder kind="error" compact title="资料加载失败" description={error} /></Panel>;

  return (
    <Panel title="联系人信息">
      <div className="basic-panel-head">
        <div><p>这是「你本人」的对外资料，用于名片、交付对接与操作日志署名，不参与任何权限判定。</p></div>
        {profile && <Badge tone="slate">账号 {profile.username}</Badge>}
      </div>
      <form onSubmit={save}>
        <div className="form-grid">
          <TextInput label="姓名" value={form.display_name} disabled={!canWrite} maxLength={64} onChange={(event) => update("display_name", event.target.value)} />
          <TextInput label="职务" value={form.job_title} disabled={!canWrite} maxLength={64} placeholder="例如：品牌运营" onChange={(event) => update("job_title", event.target.value)} />
          <TextInput label="联系电话" value={form.phone} disabled={!canWrite} maxLength={64} placeholder="座机或手机" onChange={(event) => update("phone", event.target.value)} />
          <TextInput label="微信" value={form.wechat} disabled={!canWrite} maxLength={64} placeholder="微信号，便于对接" onChange={(event) => update("wechat", event.target.value)} />
        </div>
        <div className="basic-actions">
          {dirty && <Badge tone="amber">未保存</Badge>}
          {canWrite
            ? <Button type="submit" disabled={saving || !dirty}>{saving ? "保存中…" : "保存联系人信息"}</Button>
            : <span className="basic-readonly">当前账号只能查看，不能修改联系人信息。</span>}
        </div>
      </form>
    </Panel>
  );
}

interface WayForm {
  id?: string;
  channel: string;
  value: string;
  label: string;
  is_public: boolean;
  sort_order: string;
  notes: string;
}

const EMPTY_WAY: WayForm = { channel: "phone", value: "", label: "", is_public: true, sort_order: "0", notes: "" };

function WaysTab({ projectId, canWrite, onNotice }: { projectId: string; canWrite: boolean; onNotice: (message: string) => void }) {
  const [rows, setRows] = useState<ProjectContactRecord[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<WayForm | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    workbenchClient.projectContacts(projectId)
      .then((list) => { if (active) { setRows(list); setError(""); } })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "对外渠道加载失败"); })
      .finally(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, [projectId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form || !canWrite) return;
    if (!form.value.trim()) { onNotice("渠道值不能为空"); return; }
    setSaving(true);
    const payload = {
      channel: form.channel,
      value: form.value.trim(),
      label: form.label.trim() || null,
      is_public: form.is_public,
      sort_order: Number(form.sort_order) || 0,
      notes: form.notes.trim() || null,
    };
    try {
      if (form.id) {
        const updated = await workbenchClient.updateProjectContact(projectId, form.id, payload);
        setRows((current) => current.map((row) => row.id === updated.id ? updated : row));
        onNotice("渠道已更新");
      } else {
        const created = await workbenchClient.createProjectContact(projectId, payload);
        setRows((current) => [...current, created]);
        onNotice("渠道已新增");
      }
      setForm(null);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "渠道保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function togglePublic(row: ProjectContactRecord) {
    if (!canWrite) return;
    try {
      const updated = await workbenchClient.updateProjectContact(projectId, row.id, { is_public: !row.is_public });
      setRows((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "状态切换失败");
    }
  }

  async function remove(row: ProjectContactRecord) {
    if (!canWrite) return;
    if (!window.confirm(`删除渠道「${row.channel_label} · ${row.value}」？`)) return;
    try {
      await workbenchClient.deleteProjectContact(projectId, row.id);
      setRows((current) => current.filter((item) => item.id !== row.id));
      if (form?.id === row.id) setForm(null);
      onNotice("渠道已删除");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "删除失败");
    }
  }

  return (
    <Panel title="对外渠道">
      <div className="basic-panel-head">
        <div>
          <p>
            公众号、小红书、抖音、门店电话等多渠道露面方式。对外「官方值」（业务电话 / 售后热线 / 企业邮箱）
            只维护在企业档案，这里不复制，避免同一份口径两处各写一遍。
          </p>
        </div>
        <div className="basic-panel-actions">
          <Badge tone="slate">{rows.filter((row) => row.is_public).length} 条对外公开</Badge>
          {canWrite && !form && <Button icon="plus" onClick={() => setForm({ ...EMPTY_WAY })}>新增渠道</Button>}
        </div>
      </div>

      {form && (
        <form className="basic-cert-form" onSubmit={submit}>
          <div className="basic-cert-form-head">
            <strong>{form.id ? "编辑渠道" : "新增渠道"}</strong>
            <Button type="button" variant="quiet" onClick={() => setForm(null)}>取消</Button>
          </div>
          <div className="form-grid">
            <SelectInput label="渠道" value={form.channel} onChange={(event) => setForm({ ...form, channel: event.target.value })}>
              {CHANNEL_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </SelectInput>
            <TextInput label="渠道值 *" value={form.value} maxLength={255} placeholder="号码 / 邮箱 / 账号名 / 链接 / 地址" onChange={(event) => setForm({ ...form, value: event.target.value })} />
            <TextInput label="备注名" value={form.label} maxLength={64} placeholder="例如：番禺校区前台" onChange={(event) => setForm({ ...form, label: event.target.value })} />
            <SelectInput label="对外公开" value={form.is_public ? "true" : "false"} onChange={(event) => setForm({ ...form, is_public: event.target.value === "true" })}>
              <option value="true">对外公开</option>
              <option value="false">仅内部使用</option>
            </SelectInput>
            <TextInput label="排序" type="number" min={0} value={form.sort_order} onChange={(event) => setForm({ ...form, sort_order: event.target.value })} />
          </div>
          <label className="field"><span className="field-label">备注</span><textarea className="text-input" rows={2} maxLength={5000} value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
          <div className="basic-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : form.id ? "保存修改" : "确认新增"}</Button></div>
        </form>
      )}

      {!loaded && <StatePlaceholder kind="loading" compact title="正在加载对外渠道" />}
      {loaded && error && <StatePlaceholder kind="error" compact title="对外渠道加载失败" description={error} />}
      {loaded && !error && rows.length === 0 && (
        <StatePlaceholder kind="empty" compact title="还没有登记对外渠道" description="公众号、小红书、抖音这些账号名登记后，生成与投放时才能引用到正确入口。" action={canWrite ? <Button onClick={() => setForm({ ...EMPTY_WAY })}>新增第一条</Button> : undefined} />
      )}
      {loaded && !error && rows.length > 0 && (
        <div className="basic-cert-table" role="table" aria-label="对外渠道列表">
          <div className="basic-cert-row is-head" role="row">
            <span role="columnheader">渠道 / 备注</span>
            <span role="columnheader">值</span>
            <span role="columnheader">可见性</span>
            <span role="columnheader">排序</span>
            <span role="columnheader">操作</span>
          </div>
          {rows.map((row) => (
            <div className="basic-cert-row" role="row" key={row.id}>
              <span role="cell" className="basic-cert-name">
                <strong>{row.channel_label}</strong>
                <small>{row.label ?? "—"}</small>
              </span>
              <span role="cell" className="basic-cert-meta"><span>{row.value}</span><small>{row.notes ?? ""}</small></span>
              <span role="cell"><Badge tone={row.is_public ? "green" : "slate"}>{row.is_public ? "对外公开" : "仅内部"}</Badge></span>
              <span role="cell"><Badge tone="slate">{row.sort_order}</Badge></span>
              <span role="cell" className="basic-cert-ops">
                {canWrite && <Button variant="quiet" onClick={() => setForm({ id: row.id, channel: row.channel, value: row.value, label: row.label ?? "", is_public: row.is_public, sort_order: String(row.sort_order), notes: row.notes ?? "" })}>编辑</Button>}
                {canWrite && <Button variant="quiet" onClick={() => void togglePublic(row)}>{row.is_public ? "转内部" : "转公开"}</Button>}
                {canWrite && <Button variant="quiet" onClick={() => void remove(row)}>删除</Button>}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function CertificationsTab({ projectId, canWrite, onNotice }: { projectId: string; canWrite: boolean; onNotice: (message: string) => void }) {
  const [rows, setRows] = useState<CertificationRecord[]>([]);
  const [loadedFor, setLoadedFor] = useState("");
  const [error, setError] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [form, setForm] = useState<CertForm | null>(null);
  const [saving, setSaving] = useState(false);

  const loading = loadedFor !== `${projectId}:${includeInactive}`;

  useEffect(() => {
    let active = true;
    workbenchClient.certifications(projectId, includeInactive)
      .then((list) => { if (active) { setRows(list); setError(""); } })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "资质加载失败"); })
      .finally(() => { if (active) setLoadedFor(`${projectId}:${includeInactive}`); });
    return () => { active = false; };
  }, [projectId, includeInactive]);

  const stats = useMemo(() => ({
    expiring: rows.filter((row) => row.status === "expiring").length,
    expired: rows.filter((row) => row.status === "expired").length,
  }), [rows]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form || !canWrite) return;
    if (!form.name.trim()) { onNotice("资质名称不能为空"); return; }
    setSaving(true);
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      category: form.category.trim() || null,
      issuer: form.issuer.trim() || null,
      cert_no: form.cert_no.trim() || null,
      issued_on: form.issued_on || null,
      expires_on: form.expires_on || null,
      evidence_url: form.evidence_url.trim() || null,
      notes: form.notes.trim() || null,
    };
    try {
      if (form.id) {
        const updated = await workbenchClient.updateCertification(projectId, form.id, { ...payload, is_active: form.is_active });
        setRows((current) => current.map((row) => row.id === updated.id ? updated : row));
        onNotice("资质已更新");
      } else {
        const created = await workbenchClient.createCertification(projectId, payload);
        setRows((current) => [created, ...current]);
        onNotice("资质已新增");
      }
      setForm(null);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "资质保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: CertificationRecord) {
    if (!canWrite) return;
    if (!window.confirm(`删除资质「${row.name}」？删除后不可恢复。`)) return;
    try {
      await workbenchClient.deleteCertification(projectId, row.id);
      setRows((current) => current.filter((item) => item.id !== row.id));
      if (form?.id === row.id) setForm(null);
      onNotice("资质已删除");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "删除失败");
    }
  }

  async function toggleActive(row: CertificationRecord) {
    if (!canWrite) return;
    try {
      const updated = await workbenchClient.updateCertification(projectId, row.id, { is_active: !row.is_active });
      setRows((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "状态切换失败");
    }
  }

  function edit(row: CertificationRecord) {
    setForm({
      id: row.id,
      name: row.name,
      category: row.category ?? "",
      issuer: row.issuer ?? "",
      cert_no: row.cert_no ?? "",
      issued_on: row.issued_on ?? "",
      expires_on: row.expires_on ?? "",
      evidence_url: row.evidence_url ?? "",
      notes: row.notes ?? "",
      is_active: row.is_active,
    });
  }

  return (
    <Panel title="资质证书">
      <div className="basic-panel-head">
        <div>
          <p>营业执照、办学许可、行业认证等。到期状态由后端按到期日现算，60 天内标黄，过期标红；不做定时任务刷新。</p>
        </div>
        <div className="basic-panel-actions">
          {(stats.expiring > 0 || stats.expired > 0) && (
            <>
              {stats.expiring > 0 && <Badge tone="amber">{stats.expiring} 项即将到期</Badge>}
              {stats.expired > 0 && <Badge tone="red">{stats.expired} 项已过期</Badge>}
            </>
          )}
          <label className="basic-check"><input type="checkbox" checked={includeInactive} onChange={(event) => setIncludeInactive(event.target.checked)} />含已停用</label>
          {canWrite && !form && <Button icon="plus" onClick={() => setForm({ ...EMPTY_CERT })}>新增资质</Button>}
        </div>
      </div>

      {form && (
        <form className="basic-cert-form" onSubmit={submit}>
          <div className="basic-cert-form-head">
            <strong>{form.id ? "编辑资质" : "新增资质"}</strong>
            <Button type="button" variant="quiet" onClick={() => setForm(null)}>取消</Button>
          </div>
          <div className="form-grid">
            <TextInput label="资质名称 *" value={form.name} maxLength={255} placeholder="例如：办学许可证" onChange={(event) => setForm({ ...form, name: event.target.value })} />
            <TextInput label="类别" value={form.category} maxLength={64} placeholder="例如：证照 / 行业认证" onChange={(event) => setForm({ ...form, category: event.target.value })} />
            <div className="basic-cat-presets">
              {CERT_CATEGORY_PRESETS.map((preset) => (
                <button type="button" key={preset} className={`basic-cat-chip${form.category === preset ? " active" : ""}`} onClick={() => setForm({ ...form, category: preset })}>{preset}</button>
              ))}
            </div>
            <TextInput label="发证机构" value={form.issuer} maxLength={255} onChange={(event) => setForm({ ...form, issuer: event.target.value })} />
            <TextInput label="证书编号" value={form.cert_no} maxLength={128} onChange={(event) => setForm({ ...form, cert_no: event.target.value })} />
            <TextInput label="发证日期" type="date" value={form.issued_on} onChange={(event) => setForm({ ...form, issued_on: event.target.value })} />
            <TextInput label="到期日期" type="date" value={form.expires_on} onChange={(event) => setForm({ ...form, expires_on: event.target.value })} />
            <TextInput label="证据链接" value={form.evidence_url} maxLength={512} placeholder="https://…" onChange={(event) => setForm({ ...form, evidence_url: event.target.value })} />
          </div>
          <label className="field"><span className="field-label">备注</span><textarea className="text-input" rows={3} maxLength={5000} value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
          {form.id && (
            <SelectInput label="状态" value={form.is_active ? "true" : "false"} onChange={(event) => setForm({ ...form, is_active: event.target.value === "true" })}>
              <option value="true">启用</option>
              <option value="false">停用（不在有效资质里出现）</option>
            </SelectInput>
          )}
          <div className="basic-actions">
            <Button type="submit" disabled={saving}>{saving ? "保存中…" : form.id ? "保存修改" : "确认新增"}</Button>
          </div>
        </form>
      )}

      {loading && <StatePlaceholder kind="loading" compact title="正在加载资质" />}
      {!loading && error && <StatePlaceholder kind="error" compact title="资质加载失败" description={error} action={<Button variant="secondary" onClick={() => setLoadedFor("")}>重新加载</Button>} />}
      {!loading && !error && rows.length === 0 && (
        <StatePlaceholder kind="empty" compact title="还没有登记资质" description="营业执照与办学许可是对外可信度的基础；登记后到期前 60 天会自动标黄。" action={canWrite ? <Button onClick={() => setForm({ ...EMPTY_CERT })}>新增第一条</Button> : undefined} />
      )}
      {!loading && !error && rows.length > 0 && (
        <div className="basic-cert-table" role="table" aria-label="资质列表">
          <div className="basic-cert-row is-head" role="row">
            <span role="columnheader">资质</span>
            <span role="columnheader">发证机构 / 编号</span>
            <span role="columnheader">有效期</span>
            <span role="columnheader">状态</span>
            <span role="columnheader">操作</span>
          </div>
          {rows.map((row) => {
            const status = certStatus(row);
            return (
              <div className="basic-cert-row" role="row" key={row.id}>
                <span role="cell" className="basic-cert-name">
                  <strong>{row.name}</strong>
                  <small>{row.category ?? "未分类"}{!row.is_active && " · 已停用"}</small>
                </span>
                <span role="cell" className="basic-cert-meta"><span>{row.issuer ?? "—"}</span><small>{row.cert_no ?? "—"}</small></span>
                <span role="cell" className="basic-cert-meta"><span>{row.issued_on ?? "—"} → {row.expires_on ?? "长期"}</span></span>
                <span role="cell"><Badge tone={status.tone}>{status.label}</Badge></span>
                <span role="cell" className="basic-cert-ops">
                  {canWrite && <Button variant="quiet" onClick={() => edit(row)}>编辑</Button>}
                  {canWrite && <Button variant="quiet" onClick={() => void toggleActive(row)}>{row.is_active ? "停用" : "启用"}</Button>}
                  {canWrite && <Button variant="quiet" onClick={() => void remove(row)}>删除</Button>}
                  {row.evidence_url && <a className="basic-cert-link" href={row.evidence_url} target="_blank" rel="noreferrer">证据</a>}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
