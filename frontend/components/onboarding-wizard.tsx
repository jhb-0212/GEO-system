"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { IndustryPresetOption, IndustryStatus, OnboardingApplyResult, OnboardingPreview } from "@/lib/workbench/types";

/**
 * 开通向导：8 个字段 → 预览派生 → 确认落草稿。
 *
 * 三条纪律在这里也要看得见：
 * - 行业预设不预选，未选时明确提示，不偷偷套用别的行业；
 * - 预览只算不写，apply 之前用户能看到会派生多少题/渠道/任务；
 * - 结果全是草稿，任务只在存在引擎入口时创建，不自动采集。
 */

const splitLines = (value: string) => value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

function pickPreset(options: string[], current: string): string {
  return options.includes(current) ? current : "";
}

export function OnboardingWorkspace({ mode, projectId, canRead, canConfirm, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canConfirm: boolean; onNotice: (message: string) => void;
}) {
  const [status, setStatus] = useState<IndustryStatus | null>(null);
  const [presets, setPresets] = useState<IndustryPresetOption[]>([]);
  const [brandName, setBrandName] = useState("");
  const [aliases, setAliases] = useState("");
  const [domains, setDomains] = useState("");
  const [region, setRegion] = useState("");
  const [preset, setPreset] = useState("");
  const [products, setProducts] = useState("");
  const [competitors, setCompetitors] = useState("");
  const [questionCount, setQuestionCount] = useState(10);
  const [samples, setSamples] = useState(1);
  const [preview, setPreview] = useState<OnboardingPreview | null>(null);
  const [applied, setApplied] = useState<OnboardingApplyResult | null>(null);
  const [busy, setBusy] = useState<"preview" | "apply" | "">("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.industryStatus(projectId), workbenchClient.industryPresets(projectId)])
      .then(([current, options]) => {
        if (!active) return;
        setStatus(current);
        setPresets(options);
        // 已选行业就沿用；未选时保持空，让用户自己选，不默认教育。
        setPreset(pickPreset(options.map((item: IndustryPresetOption) => item.code), current.selected ? current.preset_code : ""));
        setError("");
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "行业配置加载失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, canRead, projectId]);

  const payload = useMemo(() => {
    const competitorLines = splitLines(competitors);
    const competitorItems = competitorLines.map((line) => {
      const [name, domain] = line.split(/[|｜]/).map((part) => part.trim());
      return { name, domain: domain || null };
    });
    return {
      brand: { name: brandName.trim(), aliases: splitLines(aliases), domains: splitLines(domains), region: region.trim() },
      industry_preset: preset,
      products: splitLines(products),
      competitors: competitorItems,
      engines: [],
      question_count: questionCount,
      samples_per_cell: samples,
    };
  }, [brandName, aliases, domains, region, preset, products, competitors, questionCount, samples]);

  async function runPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canRead) return;
    setBusy("preview");
    setError("");
    setApplied(null);
    try {
      setPreview(await workbenchClient.onboardingPreview(projectId, payload));
    } catch (cause) {
      setPreview(null);
      setError(cause instanceof Error ? cause.message : "预览失败");
    } finally {
      setBusy("");
    }
  }

  async function runApply() {
    if (!preview || !canConfirm) return;
    setBusy("apply");
    setError("");
    try {
      const result = await workbenchClient.onboardingApply(projectId, payload);
      setApplied(result);
      onNotice(`已落草稿：题目 ${result.questions.total}、渠道 ${result.channels.total}、任务 ${result.tasks_created}`);
      setStatus(await workbenchClient.industryStatus(projectId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "确认失败");
    } finally {
      setBusy("");
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">开通向导仅在真实接口模式可用（演示模式不会写入）。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有开通向导的查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel brand-summary-panel">
      <div className="panel-heading">
        <div>
          <h3>当前行业口径</h3>
          <p>{status?.selected
            ? `${status.preset_name}（${status.preset_code}）；规则来自预设，项目可在策略层覆盖`
            : "未选择行业预设：系统只跑通用中性规则，不含任何行业词表"}</p>
        </div>
        {status?.selected ? <Badge tone="green">已选行业</Badge> : <Badge tone="amber">未选行业</Badge>}
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && !status && <p className="knowledge-empty">正在加载行业配置…</p>}
      {status?.requirements?.length ? <div className="knowledge-list">
        {status.requirements.map((item) => <div className="knowledge-item" key={item.key}>
          <span>
            <strong>{item.label}</strong>
            <small>{item.key}{item.required ? " · 必填" : " · 可选"}</small>
          </span>
          <span className="knowledge-actions"><Badge tone={item.required ? "blue" : "slate"}>{item.required ? "必填" : "可选"}</Badge></span>
        </div>)}
      </div> : null}
    </Panel>

    <Panel className="knowledge-editor-panel">
      <div className="panel-heading">
        <div><h3>填写开通资料</h3><p>约 5 分钟；预览只算不写，确认后才落草稿，不自动采集</p></div>
        <Icon name="spark" size={18}/>
      </div>
      <form onSubmit={runPreview}>
        <label className="field"><span className="field-label">品牌正式名（必填）</span>
          <input className="text-input" value={brandName} onChange={(event) => setBrandName(event.target.value)} maxLength={255} placeholder="品牌在对外材料里的正式名称" required/>
        </label>
        <label className="field"><span className="field-label">品牌别名（每行一个）</span>
          <textarea className="text-input knowledge-textarea short" value={aliases} onChange={(event) => setAliases(event.target.value)} rows={2} placeholder={"常用简称\n英文名"}/>
        </label>
        <label className="field"><span className="field-label">官网与自有域名（每行一个）</span>
          <textarea className="text-input knowledge-textarea short" value={domains} onChange={(event) => setDomains(event.target.value)} rows={2} placeholder={"example.com\nexample.com.cn"} required/>
        </label>
        <label className="field"><span className="field-label">地区 / 服务范围（必填）</span>
          <input className="text-input" value={region} onChange={(event) => setRegion(event.target.value)} placeholder="广州 / 广东 / 全国" required/>
        </label>
        <label className="field"><span className="field-label">行业预设（必填，不自动套用）</span>
          <select className="text-input" value={preset} onChange={(event) => setPreset(event.target.value)} required>
            <option value="">请选择行业</option>
            {presets.map((item) => <option key={item.code} value={item.code}>{item.name}（{item.code}）</option>)}
          </select>
        </label>
        <label className="field"><span className="field-label">产品线 3–8 条（每行一个）</span>
          <textarea className="text-input knowledge-textarea short" value={products} onChange={(event) => setProducts(event.target.value)} rows={4} required placeholder={"产品/服务一\n产品/服务二\n产品/服务三"}/>
        </label>
        <label className="field"><span className="field-label">竞品 3–5 个（每行「名称|域名」）</span>
          <textarea className="text-input knowledge-textarea short" value={competitors} onChange={(event) => setCompetitors(event.target.value)} rows={4} required placeholder={"竞品甲|a.example\n竞品乙|b.example\n竞品丙|c.example"}/>
        </label>
        <label className="field"><span className="field-label">问题条数 8–12</span>
          <input className="text-input" type="number" min={8} max={12} value={questionCount} onChange={(event) => setQuestionCount(Number(event.target.value) || 10)}/>
        </label>
        <label className="field"><span className="field-label">每格样本 1–5</span>
          <input className="text-input" type="number" min={1} max={5} value={samples} onChange={(event) => setSamples(Number(event.target.value) || 1)}/>
        </label>
        <p className="knowledge-footnote">目标引擎暂不在此勾选：未选引擎时只建首轮轮次、不建任务；到「AI 平台入口」里确认入口后再执行。</p>
        <div className="knowledge-actions">
          <Button type="submit" disabled={busy !== ""}>{busy === "preview" ? "正在预览…" : "预览派生结果"}</Button>
          {preview && <Button type="button" variant="primary" disabled={busy !== "" || !canConfirm} onClick={runApply}>
            {busy === "apply" ? "正在确认…" : canConfirm ? "确认落草稿" : "无确认权限"}
          </Button>}
        </div>
      </form>
    </Panel>

    {preview && <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div>
          <h3>派生结果（尚未写入）</h3>
          <p>{preview.preset.name} · 题目 {preview.derived.questions.length} · 渠道 {preview.derived.channels.length} · 首轮格数 {preview.derived.plan.cells}</p>
        </div>
        <Badge tone="amber">待确认</Badge>
      </div>
      <div className="knowledge-list">
        {preview.derived.questions.map((item) => <div className="knowledge-item" key={item.code}>
          <span><strong>{item.code}</strong><small>{item.text}</small></span>
          <span className="knowledge-actions"><Badge tone="slate">{item.question_type}</Badge></span>
        </div>)}
      </div>
      <p className="knowledge-footnote">渠道（{preview.derived.channels.length} 个，全部待准入）：{preview.derived.channels.map((item) => item.name).join("、")}</p>
      <p className="knowledge-footnote">首轮计划：{preview.derived.plan.round_name} · 题目 {preview.derived.plan.questions} × 引擎 {Math.max(preview.derived.plan.engines.length, 1)} × 样本 {preview.derived.plan.samples_per_cell} = {preview.derived.plan.cells} 格；{preview.derived.plan.note}</p>
      {preview.warnings.map((item) => <p className="knowledge-footnote" key={item}>{item}</p>)}
    </Panel>}

    {applied && <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div>
          <h3>已落库</h3>
          <p>题目 {applied.questions.total}（新增 {applied.questions.created}） · 渠道 {applied.channels.total}（新增 {applied.channels.created}） · 竞品 {applied.competitors.total} · 任务 {applied.tasks_created}</p>
        </div>
        <Badge tone="green">草稿已建立</Badge>
      </div>
      {applied.warnings.map((item) => <p className="knowledge-footnote" key={item}>{item}</p>)}
      <p className="knowledge-footnote">下一步：在「监测问题与关键词」「渠道台账」里复核草稿，再到「监测任务」执行首轮。</p>
    </Panel>}
  </div>;
}
