"use client";

import { useEffect, useMemo, useState } from "react";

import { Badge, Button, Icon, Panel, SelectInput, TextInput } from "../ui";
import { StatePlaceholder } from "../states";
import { GaugeArc } from "../viz-kit";
import { workbenchClient, WorkbenchApiError } from "@/lib/workbench/client";
import type { CompanyProduct, CompanyProfileRecord } from "@/lib/workbench/types";

const LIST_FIELDS = [
  { key: "industries", label: "行业类别", hint: "每行一条，例如：教育培训 / 人工智能" },
  { key: "regions", label: "覆盖地区", hint: "每行一条，例如：广州 / 珠三角" },
  { key: "stores", label: "线下网点", hint: "每行一条，写「城市 + 门店/校区」" },
] as const;

type ListKey = (typeof LIST_FIELDS)[number]["key"];

const COMPANY_STEPS = [
  { title: "主体信息", hint: "公司名称是唯一必填项" },
  { title: "联系方式与业务范围", hint: "电话、邮箱、行业与覆盖地区" },
  { title: "对外文案", hint: "公司介绍、创始人和品牌故事" },
  { title: "产品与状态", hint: "产品条目和档案启停" },
  { title: "对外画像", hint: "企业 / 招聘 / 会议 / 活动四套口径" },
] as const;

// 四套画像的 kind 是后端固定枚举：新增会改变表结构，所以这里不放开成任意字符串。
type ViewKind = "company" | "recruit" | "meeting" | "activity";
const VIEW_ORDER: ViewKind[] = ["company", "recruit", "meeting", "activity"];
const VIEW_META: Record<ViewKind, { label: string; audience: string; hint: string }> = {
  company: { label: "企业画像", audience: "企业客户、合作伙伴", hint: "对客户怎么说：我们是谁、做什么、凭什么可信" },
  recruit: { label: "招聘画像", audience: "应届生、转行候选人", hint: "对候选人怎么说：平台、训练方式、岗位出口" },
  meeting: { label: "会议画像", audience: "会议与参访方", hint: "对参会方怎么说：一页纸介绍、可讲的议题" },
  activity: { label: "活动画像", audience: "活动与公开课受众", hint: "对活动受众怎么说：亮点、参与方式、边界" },
};

interface ViewFormState {
  kind: ViewKind;
  title: string;
  audience: string;
  scenarioWords: string;
  description: string;
  cautions: string;
  is_active: boolean;
  configured: boolean;
}

/** 后端会返回齐四套（没配的给空壳）；这里仍按 kind 兜底，避免老数据缺字段时 tab 消失。 */
function emptyViews(): ViewFormState[] {
  return VIEW_ORDER.map((kind) => ({
    kind, title: "", audience: "", scenarioWords: "", description: "", cautions: "",
    is_active: true, configured: false,
  }));
}

function viewsFromRecord(record: CompanyProfileRecord): ViewFormState[] {
  return VIEW_ORDER.map((kind) => {
    const row = (record.views ?? []).find((item) => item.kind === kind);
    return {
      kind,
      title: row?.title ?? "",
      audience: row?.audience ?? "",
      scenarioWords: (row?.scenario_words ?? []).join("\n"),
      description: row?.description ?? "",
      cautions: row?.cautions ?? "",
      is_active: row?.configured ? row.is_active : true,
      configured: Boolean(row?.configured),
    };
  });
}

interface FormState {
  legal_name: string;
  brand_name: string;
  slogan: string;
  province: string;
  headcount: string;
  founded_on: string;
  business_phone: string;
  service_hotline: string;
  contact_email: string;
  description: string;
  founder_intro: string;
  highlights: string;
  pain_points: string;
  story: string;
  is_active: boolean;
  lists: Record<ListKey, string>;
}

const EMPTY_FORM: FormState = {
  legal_name: "", brand_name: "", slogan: "", province: "", headcount: "", founded_on: "",
  business_phone: "", service_hotline: "", contact_email: "",
  description: "", founder_intro: "", highlights: "", pain_points: "", story: "",
  is_active: true,
  lists: { industries: "", regions: "", stores: "" },
};

const CONFLICT_KEY = /[a-z_]+:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;

function toLines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function fromRecord(record: CompanyProfileRecord): FormState {
  return {
    legal_name: record.legal_name ?? "",
    brand_name: record.brand_name ?? "",
    slogan: record.slogan ?? "",
    province: record.province ?? "",
    headcount: record.headcount === null || record.headcount === undefined ? "" : String(record.headcount),
    founded_on: record.founded_on ?? "",
    business_phone: record.business_phone ?? "",
    service_hotline: record.service_hotline ?? "",
    contact_email: record.contact_email ?? "",
    description: record.description ?? "",
    founder_intro: record.founder_intro ?? "",
    highlights: record.highlights ?? "",
    pain_points: record.pain_points ?? "",
    story: record.story ?? "",
    is_active: record.configured ? record.is_active !== false : true,
    lists: {
      industries: (record.industries ?? []).join("\n"),
      regions: (record.regions ?? []).join("\n"),
      stores: (record.stores ?? []).join("\n"),
    },
  };
}

export function CompanyProfileWorkspace({
  mode,
  projectId,
  canRead,
  canWrite,
  onNotice,
  onNavigate,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canWrite: boolean;
  onNotice: (message: string) => void;
  /** 官网地址的写入口在品牌设置，这里只负责把用户送过去。 */
  onNavigate?: (section: "brand") => void;
}) {
  const [profile, setProfile] = useState<CompanyProfileRecord | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [products, setProducts] = useState<CompanyProduct[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState<{ message: string; keys: string[] } | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [step, setStep] = useState(0);
  const [views, setViews] = useState<ViewFormState[]>(emptyViews);
  const [viewTab, setViewTab] = useState<ViewKind>("company");
  const [viewsSaving, setViewsSaving] = useState(false);
  const [viewsDirty, setViewsDirty] = useState(false);

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  // 加载态由「当前项目是否已取过数」推导，避免在 effect 体内同步 setState。
  const loading = active && loadedFor !== projectId;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    workbenchClient.companyProfile(projectId)
      .then((record) => {
        if (cancelled) return;
        setProfile(record);
        setForm(fromRecord(record));
        setProducts(record.products ?? []);
        setViews(viewsFromRecord(record));
        setViewsDirty(false);
        setDirty(false);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "企业档案加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoadedFor(projectId);
      });
    return () => { cancelled = true; };
  }, [projectId, active]);

  const completeness = profile?.completeness ?? 0;
  const missing = profile?.missing ?? [];
  const currentView = views.find((item) => item.kind === viewTab) ?? views[0];
  const longCopyIssue = useMemo(() => {
    const issues: string[] = [];
    const check = (value: string, name: string) => {
      if (!value.trim()) return;
      const length = value.trim().length;
      if (length < 100) issues.push(`${name}只有 ${length} 字，少于 100 字无法投喂`);
      if (length > 1000) issues.push(`${name}有 ${length} 字，超过 1000 字上限`);
    };
    check(form.description, "公司介绍");
    check(form.founder_intro, "创始人介绍");
    return issues;
  }, [form.description, form.founder_intro]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setDirty(true);
    setConflict(null);
    setAcknowledged(false);
  }

  function updateList(key: ListKey, value: string) {
    setForm((current) => ({ ...current, lists: { ...current.lists, [key]: value } }));
    setDirty(true);
  }

  function updateView(kind: ViewKind, patch: Partial<Omit<ViewFormState, "kind">>) {
    setViews((current) => current.map((item) => (item.kind === kind ? { ...item, ...patch } : item)));
    setViewsDirty(true);
  }

  async function saveViews() {
    if (!canWrite) return;
    setError("");
    // 空白的画像不提交：后端按 kind 落行，空壳写进去等于给四套都建了记录，tab 会全部显示「已配置」。
    const payload = views.filter((item) =>
      item.configured || item.title.trim() || item.audience.trim() || item.scenarioWords.trim() || item.description.trim() || item.cautions.trim(),
    );
    if (!payload.length) {
      onNotice("四套画像都还是空的，先写一套再保存");
      return;
    }
    setViewsSaving(true);
    try {
      const record = await workbenchClient.saveCompanyProfileViews(
        projectId,
        payload.map((item) => ({
          kind: item.kind,
          title: item.title.trim() || null,
          audience: item.audience.trim() || null,
          scenario_words: toLines(item.scenarioWords),
          description: item.description.trim() || null,
          cautions: item.cautions.trim() || null,
          is_active: item.is_active,
        })),
      );
      setProfile(record);
      setViews(viewsFromRecord(record));
      setViewsDirty(false);
      onNotice("对外画像已保存");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "画像保存失败，请稍后再试");
    } finally {
      setViewsSaving(false);
    }
  }

  function buildPayload(ackKeys: string[]) {
    return {
      legal_name: form.legal_name.trim(),
      brand_name: form.brand_name.trim() || null,
      slogan: form.slogan.trim() || null,
      province: form.province.trim() || null,
      headcount: form.headcount.trim() ? Number(form.headcount) : null,
      founded_on: form.founded_on || null,
      business_phone: form.business_phone.trim() || null,
      service_hotline: form.service_hotline.trim() || null,
      contact_email: form.contact_email.trim() || null,
      industries: toLines(form.lists.industries),
      regions: toLines(form.lists.regions),
      stores: toLines(form.lists.stores),
      // 官网地址不发：唯一写入口是「品牌设置 → 自有域名」，这里只读展示后端派生值。
      products: products
        .filter((item) => item.name.trim())
        .map((item) => ({ name: item.name.trim(), summary: item.summary?.trim() || null, highlights: item.highlights?.trim() || null })),
      description: form.description.trim() || null,
      founder_intro: form.founder_intro.trim() || null,
      highlights: form.highlights.trim() || null,
      pain_points: form.pain_points.trim() || null,
      story: form.story.trim() || null,
      is_active: form.is_active,
      acknowledged_conflicts: ackKeys,
    };
  }

  async function submit(ackKeys: string[] = []) {
    if (!form.legal_name.trim()) {
      setError("公司名称不能为空");
      return;
    }
    if (longCopyIssue.length) {
      setError(longCopyIssue.join("；"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const record = await workbenchClient.saveCompanyProfile(projectId, buildPayload(ackKeys));
      setProfile(record);
      setForm(fromRecord(record));
      setProducts(record.products ?? []);
      setViews(viewsFromRecord(record));
      setViewsDirty(false);
      setConflict(null);
      setAcknowledged(false);
      setDirty(false);
      onNotice(`企业档案已保存，完整度 ${record.completeness}%`);
    } catch (cause) {
      if (cause instanceof WorkbenchApiError) {
        const keys = cause.message.match(CONFLICT_KEY) ?? [];
        if (keys.length) {
          setConflict({ message: cause.message, keys });
          setAcknowledged(false);
        } else {
          setError(cause.message);
        }
      } else {
        setError(cause instanceof Error ? cause.message : "保存失败，请稍后再试");
      }
    } finally {
      setSaving(false);
    }
  }

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不写企业档案" description="企业档案直接落库并参与事实冲突校验，演示数据不写正式库。切到真实接口模式后再编辑。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看企业档案" description="当前账号缺少 monitoring.read 能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="企业档案按项目独立保存；在右上角选择具体项目后再填写。" />;
  }
  if (loading) {
    return <StatePlaceholder kind="loading" title="正在加载企业档案" />;
  }

  return (
    <div className="company-layout">
      <div className="company-main">
        {error && (
          <div className="load-error" role="alert">
            <Icon name="info" size={18} />
            {error}
            <Button variant="quiet" onClick={() => setError("")}>知道了</Button>
          </div>
        )}

        {!profile?.configured && !dirty && (
          <div className="company-hint">
            <strong>尚未配置企业档案</strong>
            <p>先填公司名称与两段长文案，其余字段可以分次补。完整度只在保存后提示缺口，不阻塞保存。</p>
          </div>
        )}

        {conflict && (
          <div className="company-conflict" role="alert">
            <strong>与权威事实冲突，需要你确认</strong>
            <p>{conflict.message}</p>
            <label className="company-conflict-ack">
              <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
              我已核对该数值，确认以企业档案为准（审计会记下谁确认了哪个数）
            </label>
            <div className="knowledge-actions">
              <Button disabled={!acknowledged || saving} onClick={() => void submit(conflict.keys)}>{saving ? "保存中…" : "确认并以档案为准保存"}</Button>
              <Button variant="secondary" disabled={saving} onClick={() => { setConflict(null); setAcknowledged(false); }}>返回修改</Button>
            </div>
          </div>
        )}

        <nav className="company-steps" aria-label="企业档案填写步骤">
          {COMPANY_STEPS.map((item, index) => (
            <button key={item.title} type="button" className={`company-step${step === index ? " is-active" : ""}`} aria-current={step === index ? "step" : undefined} onClick={() => setStep(index)}>
              <span className="company-step-no">{index + 1}</span>
              <span><strong>{item.title}</strong><small>{item.hint}</small></span>
            </button>
          ))}
        </nav>

        <div hidden={step !== 0}>
        <Panel className="company-panel" title="主体信息">
          <div className="panel-heading"><div><h3>主体信息</h3><p>决定 AI 如何识别公司主体，必填项只有公司名称</p></div></div>
          <div className="form-grid">
            <TextInput label="公司名称 *" value={form.legal_name} maxLength={255} onChange={(event) => update("legal_name", event.target.value)} placeholder="与营业执照一致" />
            <TextInput label="公司品牌" value={form.brand_name} maxLength={255} onChange={(event) => update("brand_name", event.target.value)} placeholder="对外使用的品牌名" />
            <TextInput label="品牌 slogan" value={form.slogan} maxLength={255} onChange={(event) => update("slogan", event.target.value)} placeholder="一句话定位" />
            <TextInput label="所在省份" value={form.province} maxLength={64} onChange={(event) => update("province", event.target.value)} placeholder="例如：广东" />
            <TextInput label="员工规模" type="number" min={0} max={1000000} value={form.headcount} onChange={(event) => update("headcount", event.target.value)} placeholder="例如：120" />
            <TextInput label="成立日期" type="date" value={form.founded_on} onChange={(event) => update("founded_on", event.target.value)} />
          </div>
        </Panel>
        </div>

        <div hidden={step !== 1}>
        <Panel className="company-panel" title="联系方式">
          <div className="panel-heading"><div><h3>联系方式</h3><p>电话与成立日期会与事实库交叉校验，不一致时必须显式确认</p></div></div>
          <div className="form-grid">
            <TextInput label="业务电话" value={form.business_phone} maxLength={64} onChange={(event) => update("business_phone", event.target.value)} />
            <TextInput label="售后热线" value={form.service_hotline} maxLength={64} onChange={(event) => update("service_hotline", event.target.value)} />
            <TextInput label="企业邮箱" type="email" value={form.contact_email} maxLength={255} onChange={(event) => update("contact_email", event.target.value)} />
          </div>
        </Panel>

        <Panel className="company-panel" title="业务范围">
          <div className="panel-heading"><div><h3>业务范围</h3><p>列表类字段每行一条，重复项保存时自动去掉；官网域名不在这里填</p></div></div>
          <div className="form-grid company-grid-wide">
            {LIST_FIELDS.map((item) => (
              <label className="field" key={item.key}>
                <span className="field-label">{item.label}</span>
                <textarea
                  className="text-input company-textarea"
                  rows={3}
                  value={form.lists[item.key]}
                  placeholder={item.hint}
                  onChange={(event) => updateList(item.key, event.target.value)}
                />
              </label>
            ))}
          </div>
          <div className="company-derived">
            <div className="company-derived-head">
              <span className="field-label">官网地址</span>
              <Badge tone="blue">品牌设置派生·只读</Badge>
            </div>
            {(profile?.official_urls ?? []).length ? (
              <ul className="company-derived-list">
                {(profile?.official_urls ?? []).map((url) => <li key={url}>{url}</li>)}
              </ul>
            ) : (
              <p className="company-derived-empty">品牌设置里还没配自有域名，所以这一项算缺口。去「品牌设置 → 自有域名」补上，这里会自动出现。</p>
            )}
            <p className="company-derived-note">官网域名只认一个写入口：品牌设置。在这里填会被接口拒绝，避免两处各写一份、谁对说不清。</p>
            {onNavigate && (
              <Button variant="secondary" icon="arrowRight" onClick={() => { if (dirty) onNotice("企业档案有未保存的改动，去品牌设置前建议先保存"); onNavigate("brand"); }}>去品牌设置配域名</Button>
            )}
          </div>
        </Panel>
        </div>

        <div hidden={step !== 2}>
        <Panel className="company-panel" title="对外文案">
          <div className="panel-heading"><div><h3>对外文案</h3><p>公司介绍与创始人介绍 100–1000 字；其余每段 ≤500 字</p></div></div>
          <div className="form-grid company-grid-wide">
            <label className="field">
              <span className="field-label">公司介绍（≥100 字）<em className={form.description.trim().length >= 100 ? "is-ok" : "is-warn"}>{form.description.trim().length}</em></span>
              <textarea className="text-input company-textarea" rows={6} value={form.description} onChange={(event) => update("description", event.target.value)} placeholder="做什么、为谁做、凭什么可信" />
            </label>
            <label className="field">
              <span className="field-label">创始人介绍（≥100 字）<em className={form.founder_intro.trim().length >= 100 ? "is-ok" : "is-warn"}>{form.founder_intro.trim().length}</em></span>
              <textarea className="text-input company-textarea" rows={6} value={form.founder_intro} onChange={(event) => update("founder_intro", event.target.value)} placeholder="背景、经历、与业务的关系" />
            </label>
            <label className="field">
              <span className="field-label">产品/服务特点</span>
              <textarea className="text-input company-textarea" rows={3} maxLength={500} value={form.highlights} onChange={(event) => update("highlights", event.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">用户痛点</span>
              <textarea className="text-input company-textarea" rows={3} maxLength={500} value={form.pain_points} onChange={(event) => update("pain_points", event.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">品牌故事</span>
              <textarea className="text-input company-textarea" rows={3} maxLength={500} value={form.story} onChange={(event) => update("story", event.target.value)} />
            </label>
          </div>
        </Panel>
        </div>

        <div hidden={step !== 3}>
        <Panel className="company-panel" title="产品信息">
          <div className="panel-heading">
            <div><h3>产品信息</h3><p>产品名必填，摘要与卖点各 ≤500 字</p></div>
            <Button variant="secondary" icon="plus" onClick={() => { setProducts((current) => [...current, { name: "", summary: "", highlights: "" }]); setDirty(true); }}>加一条</Button>
          </div>
          {products.length === 0 ? (
            <StatePlaceholder kind="empty" compact title="还没有产品条目" description="产品是 AI 回答「你们提供什么」的主要依据，建议至少填 1 条。" />
          ) : (
            <div className="company-product-list">
              {products.map((item, index) => (
                <div className="company-product-row" key={index}>
                  <TextInput label={`产品 ${index + 1} 名称 *`} value={item.name} maxLength={120} onChange={(event) => { const value = event.target.value; setProducts((current) => current.map((row, i) => (i === index ? { ...row, name: value } : row))); setDirty(true); }} />
                  <TextInput label="摘要" value={item.summary ?? ""} maxLength={500} onChange={(event) => { const value = event.target.value; setProducts((current) => current.map((row, i) => (i === index ? { ...row, summary: value } : row))); setDirty(true); }} />
                  <TextInput label="卖点" value={item.highlights ?? ""} maxLength={500} onChange={(event) => { const value = event.target.value; setProducts((current) => current.map((row, i) => (i === index ? { ...row, highlights: value } : row))); setDirty(true); }} />
                  <Button variant="quiet" onClick={() => { setProducts((current) => current.filter((_, i) => i !== index)); setDirty(true); }}>移除</Button>
                </div>
              ))}
            </div>
          )}
        </Panel>
        </div>

        <div hidden={step !== 4}>
        <Panel className="company-panel" title="对外画像">
          <div className="panel-heading"><div><h3>对外画像</h3><p>同一家主体，对客户、候选人、参会方、活动受众的说法不一样；四套口径各自启停，一起投喂生成</p></div></div>

          <nav className="company-view-tabs" role="tablist" aria-label="对外画像">
            {views.map((item) => (
              <button
                key={item.kind}
                type="button"
                role="tab"
                aria-selected={viewTab === item.kind}
                className={`company-view-tab${viewTab === item.kind ? " is-active" : ""}`}
                onClick={() => setViewTab(item.kind)}
              >
                <strong>{VIEW_META[item.kind].label}</strong>
                <small>{item.configured ? (item.is_active ? "已配置" : "已停用") : "未配置"}</small>
              </button>
            ))}
          </nav>

          <p className="company-view-hint">{VIEW_META[currentView.kind].hint}</p>

          <div className="form-grid company-view-grid">
            <TextInput label="画像名称" value={currentView.title} maxLength={128} placeholder={VIEW_META[currentView.kind].label} onChange={(event) => updateView(currentView.kind, { title: event.target.value })} />
            <TextInput label="目标受众" value={currentView.audience} maxLength={255} placeholder={VIEW_META[currentView.kind].audience} onChange={(event) => updateView(currentView.kind, { audience: event.target.value })} />
          </div>

          <div className="form-grid company-view-grid is-split">
            <label className="field">
              <span className="field-label">场景词（每行一条，最多 30）<em className={toLines(currentView.scenarioWords).length ? "is-ok" : "is-warn"}>{toLines(currentView.scenarioWords).length}</em></span>
              <textarea className="text-input company-textarea" rows={6} value={currentView.scenarioWords} onChange={(event) => updateView(currentView.kind, { scenarioWords: event.target.value })} placeholder="例如：零基础转行 / 实训基地 / 项目制课程" />
            </label>
            <div className="company-view-stack">
              <label className="field">
                <span className="field-label">对外说法（≤1000 字）<em className={currentView.description.trim().length ? "is-ok" : "is-warn"}>{currentView.description.trim().length}</em></span>
                <textarea className="text-input company-textarea" rows={6} maxLength={1000} value={currentView.description} onChange={(event) => updateView(currentView.kind, { description: event.target.value })} placeholder="这一段会直接进投喂与生成，写「对这群人最重要的一句话 + 依据」" />
              </label>
              <label className="field">
                <span className="field-label">不要这样说（≤500 字）</span>
                <textarea className="text-input company-textarea" rows={3} maxLength={500} value={currentView.cautions} onChange={(event) => updateView(currentView.kind, { cautions: event.target.value })} placeholder="例如：不承诺就业率与薪资；不写「官方认证」这类没证据的话" />
              </label>
            </div>
          </div>

          <div className="company-view-foot">
            <label className="rounds-checkbox">
              <input type="checkbox" checked={currentView.is_active} onChange={(event) => updateView(currentView.kind, { is_active: event.target.checked })} />
              启用这套画像
            </label>
            <div className="company-actions-buttons">
              {viewsDirty && <Badge tone="amber">未保存</Badge>}
              <Button icon="check" disabled={viewsSaving || !canWrite} onClick={() => void saveViews()}>{viewsSaving ? "保存中…" : "保存四套画像"}</Button>
            </div>
          </div>
        </Panel>
        </div>

        <div className="company-step-pager">
          <span>第 {step + 1} / {COMPANY_STEPS.length} 步 · {COMPANY_STEPS[step].title}</span>
          <div>
            {step > 0 && <Button variant="secondary" onClick={() => setStep(step - 1)}>上一步</Button>}
            {step < COMPANY_STEPS.length - 1 && <Button variant="secondary" onClick={() => setStep(step + 1)}>下一步</Button>}
          </div>
        </div>

        <div className="company-actions">
          <SelectInput label="档案状态" value={form.is_active ? "true" : "false"} onChange={(event) => update("is_active", event.target.value === "true")}>
            <option value="true">启用</option>
            <option value="false">停用（不参与生成与投喂）</option>
          </SelectInput>
          <div className="company-actions-buttons">
            {dirty && <Badge tone="amber">未保存</Badge>}
            <Button icon="check" disabled={saving || !canWrite || !dirty} onClick={() => void submit()}>{saving ? "保存中…" : "保存档案"}</Button>
          </div>
        </div>
        {!canWrite && <p className="knowledge-footnote">当前账号只能查看（缺 brand.manage 能力），需要编辑请联系项目管理员。</p>}
      </div>

      <aside className="company-side">
        <div className="company-side-card">
          <GaugeArc value={completeness / 100} label="档案完整度" caption={missing.length ? `还缺 ${missing.length} 项` : "16 项已齐全"} tone={completeness >= 90 ? "positive" : completeness >= 60 ? "warning" : "danger"} />
          <p className="company-side-note">完整度 = 16 个必填项的占比，由后端计算；这里不参与任何加权总分。</p>
          {profile?.updated_at && <p className="company-side-time">最近保存：{profile.updated_at}</p>}
        </div>

        <div className="company-side-card">
          <div className="g-tile-head"><span className="g-tile-label">缺口清单</span><Badge tone={missing.length ? "amber" : "green"}>{missing.length ? `${missing.length} 项` : "齐全"}</Badge></div>
          {missing.length ? (
            <ul className="company-missing">
              {missing.map((item) => <li key={item}><Icon name="info" size={13} />{item}</li>)}
            </ul>
          ) : (
            <p className="company-side-note">16 项必填全部已填，可以进入生成与投喂环节。</p>
          )}
        </div>

        <div className="company-side-card">
          <div className="g-tile-head"><span className="g-tile-label">与事实库的关系</span></div>
          <p className="company-side-note">
            档案不复制事实。电话、成立日期与 <code>facts</code> 不一致时接口会拒绝保存，只有人工确认后才放行，并在审计里记下确认人。
          </p>
        </div>
      </aside>
    </div>
  );
}
