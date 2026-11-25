"use client";

import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { formatDateTime } from "@/lib/workbench/format";
import type { MonthlyReport } from "@/lib/workbench/types";

type ShareMeta = {
  brand_name: string;
  brand_logo_url: string | null;
  accent_color: string;
  contact_text: string | null;
  month: string;
  period_start: string | null;
  period_end: string | null;
  captured_at: string;
  requires_password: boolean;
  expires_at: string;
};

type SharePayload = ShareMeta & {
  snapshot_hash: string;
  report: MonthlyReport;
  view_count: number;
};

const rate = (value: number | null | undefined) => value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
const citationRate = (observable: number | null | undefined, value: number | null | undefined) => observable === 0 ? "不可观测" : rate(value);

async function responseError(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (response.status === 404) return "链接不可用：可能已过期、被吊销或地址不完整。";
  if (response.status === 429) return "访问过于频繁，请稍后再试。";
  return payload?.error?.message ?? "报告加载失败，请稍后再试。";
}

export function PublicReportClient({ token }: { token: string }) {
  const [meta, setMeta] = useState<ShareMeta | null>(null);
  const [payload, setPayload] = useState<SharePayload | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function loadMeta() {
      setLoading(true);
      try {
        const response = await fetch(`/share/${encodeURIComponent(token)}/api`, { cache: "no-store" });
        if (!response.ok) {
          if (active) setError(await responseError(response));
          return;
        }
        const envelope = await response.json();
        const next = envelope.data as ShareMeta;
        if (!active) return;
        setMeta(next);
        if (!next.requires_password) {
          const access = await fetch(`/share/${encodeURIComponent(token)}/api`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: null }),
          });
          if (!access.ok) {
            if (active) setError(await responseError(access));
            return;
          }
          const body = await access.json();
          if (active) setPayload(body.data as SharePayload);
        }
      } catch {
        if (active) setError("无法连接报告服务，请稍后再试。");
      } finally {
        if (active) setLoading(false);
      }
    }
    void loadMeta();
    return () => { active = false; };
  }, [token]);

  async function unlock(event?: FormEvent) {
    event?.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/share/${encodeURIComponent(token)}/api`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: password.trim() || null }),
      });
      if (!response.ok) {
        setError(await responseError(response));
        return;
      }
      const body = await response.json();
      setPayload(body.data as SharePayload);
    } catch {
      setError("无法连接报告服务，请稍后再试。");
    } finally {
      setLoading(false);
    }
  }

  if (!meta && !error) {
    return <main className="customer-report-shell"><div className="customer-report-loading">正在打开报告…</div></main>;
  }

  if (!meta && error) {
    return <main className="customer-report-shell"><section className="customer-report-gate">
      <span className="customer-report-mark">报告</span>
      <h1>链接不可用</h1>
      <p>{error}</p>
    </section></main>;
  }

  if (meta && !payload) {
    const style = { "--report-accent": meta.accent_color } as CSSProperties;
    return <main className="customer-report-shell" style={style}>
      <section className="customer-report-gate">
        <span className="customer-report-mark">{meta.brand_logo_url ? <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={meta.brand_logo_url} alt="" />
        </> : meta.brand_name.slice(0, 1)}</span>
        <small>{meta.brand_name}</small>
        <h1>{meta.month} 月度报告</h1>
        <p>该报告为只读客户版本，请输入访问密码。</p>
        <form onSubmit={(event) => void unlock(event)}>
          <input
            type="password"
            value={password}
            autoFocus
            maxLength={72}
            placeholder="访问密码"
            onChange={(event) => setPassword(event.target.value)}
          />
          <button type="submit" disabled={loading}>{loading ? "正在验证…" : "打开报告"}</button>
        </form>
        {error && <p className="customer-report-error" role="alert">{error}</p>}
        <span className="customer-report-fine">有效至 {formatDateTime(meta.expires_at)}</span>
      </section>
    </main>;
  }

  if (!meta || !payload) return null;
  const report = payload.report;
  const breakdown = report.answer_breakdown;
  const style = { "--report-accent": payload.accent_color } as CSSProperties;

  return <main className="customer-report-shell" style={style}>
    <header className="customer-report-header">
      <div className="customer-report-brand">
        <span className="customer-report-mark">{payload.brand_logo_url ? <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={payload.brand_logo_url} alt="" />
        </> : payload.brand_name.slice(0, 1)}</span>
        <div><small>{payload.brand_name}</small><h1>GEO 月度报告</h1></div>
      </div>
      <div className="customer-report-period">
        <strong>{payload.month}</strong>
        <span>只读客户版本</span>
      </div>
    </header>

    <section className="customer-report-hero">
      <p className="customer-report-eyebrow">AI 搜索可见性 · 月度复盘</p>
      <h2>{payload.brand_name}在 AI 回答中的呈现</h2>
      <p>本报告聚合 {formatDateTime(report.period_start)} 至 {formatDateTime(report.period_end)} 的监测样本、引用与发布结果。所有指标保留分子与分母，不合成品牌总分。</p>
    </section>

    <section className="customer-report-metrics">
      <div><span>监测任务</span><strong>{report.tasks.total}</strong><small>完成率 {rate(report.tasks.completion_rate)}</small></div>
      <div><span>有效回答</span><strong>{report.answers.valid_answers}</strong><small>总样本 {report.answers.total_samples}</small></div>
      <div><span>通用题自然发现率</span><strong>{rate(breakdown?.general.brand_mention_rate ?? report.answers.brand_mention_rate)}</strong><small>用户未提品牌时被提及</small></div>
      <div><span>品牌题识别率</span><strong>{rate(breakdown?.brand.brand_identified_rate ?? report.answers.brand_identified_rate)}</strong><small>品牌题中准确识别</small></div>
      <div><span>引用率</span><strong>{citationRate(report.answers.citation_observable_answers, report.answers.citation_rate)}</strong><small>有效回答为分母</small></div>
      <div><span>发布结案</span><strong>{report.published_receipts}</strong><small>真实回执，不含测试</small></div>
    </section>

    <section className="customer-report-section">
      <div className="customer-report-section-head"><small>01</small><h3>监测执行</h3></div>
      <div className="customer-report-split">
        <dl><dt>任务完成</dt><dd>{report.tasks.done}</dd><dt>失败</dt><dd>{report.tasks.failed}</dd><dt>运行中</dt><dd>{report.tasks.running}</dd><dt>待执行</dt><dd>{report.tasks.pending}</dd></dl>
        <p>失败率 {rate(report.answers.failure_rate)}；24 小时新鲜样本率 {rate(report.answers.fresh_24h_rate)}；题目覆盖 {rate(report.answers.prompt_coverage)}。失败与不可观测样本单列，不并入品牌表现。</p>
      </div>
    </section>

    <section className="customer-report-section">
      <div className="customer-report-section-head"><small>02</small><h3>回答表现</h3></div>
      <div className="customer-report-answer-grid">
        <div><span>通用题</span><h4>自然发现</h4><strong>{rate(breakdown?.general.brand_mention_rate ?? report.answers.brand_mention_rate)}</strong><p>有效 {breakdown?.general.valid_answers ?? report.answers.valid_answers} · 提及 {breakdown?.general.brand_mentioned_answers ?? report.answers.brand_mentioned_answers}</p></div>
        <div><span>品牌题</span><h4>品牌识别</h4><strong>{rate(breakdown?.brand.brand_identified_rate ?? report.answers.brand_identified_rate)}</strong><p>有效 {breakdown?.brand.valid_answers ?? report.answers.valid_answers} · 提及 {breakdown?.brand.brand_mentioned_answers ?? report.answers.brand_mentioned_answers}</p></div>
      </div>
    </section>

    <section className="customer-report-section">
      <div className="customer-report-section-head"><small>03</small><h3>引用观测</h3></div>
      <div className="customer-report-split">
        <dl><dt>可观测样本</dt><dd>{report.answers.citation_observable_answers ?? "—"}</dd><dt>不可观测</dt><dd>{report.answers.citation_unobservable_answers ?? "—"}</dd><dt>含引用回答</dt><dd>{report.answers.citation_answers}</dd></dl>
        <p>引用率仅统计人工确认的品牌相关引用。当前引擎不支持引用观测时标为“不可观测”，不按 0% 处理。发布结案 {report.published_receipts} 条，测试地址不计入真实发布。</p>
      </div>
    </section>

    <section className="customer-report-section">
      <div className="customer-report-section-head"><small>04</small><h3>入口对照</h3></div>
      {report.entry_breakdown?.length ? <div className="customer-report-answer-grid">
        {report.entry_breakdown.map((item) => <div key={item.entry_id}>
          <span>{item.engine_name} · {item.entry_label}</span>
          <h4>{item.entry_name}</h4>
          <strong>{rate(item.brand_mention_rate)}</strong>
          <p>有效 {item.valid_answers} · 被推荐 {rate(item.brand_recommendation_rate ?? null)} · Top3 {rate(item.top3_rate ?? null)} · 引用 {citationRate(item.citation_observable_answers, item.citation_rate)}</p>
        </div>)}
      </div> : <p>本报告未包含入口明细；若为历史冻结报告，说明冻结时尚未启用入口拆分。</p>}
      {(report.entry_breakdown?.length ?? 0) > 0 && <p className="customer-report-note">同一引擎的网页端与手机客户端分行展示，每行独立分母；本报告不把两端回答平均成单一引擎结论。</p>}
    </section>

    {report.leads && <section className="customer-report-section">
      <div className="customer-report-section-head"><small>05</small><h3>咨询与转化</h3></div>
      <div className="customer-report-metrics is-compact">
        <div><span>咨询总量</span><strong>{report.leads.total}</strong></div>
        <div><span>有效线索</span><strong>{report.leads.valid}</strong></div>
        <div><span>已联系</span><strong>{report.leads.contacted}</strong></div>
        <div><span>已报名</span><strong>{report.leads.enrolled}</strong></div>
        <div><span>转化率</span><strong>{rate(report.leads.conversion_rate)}</strong></div>
      </div>
      <p className="customer-report-note">可追踪访问 {report.leads.ai_attribution.trackable_visits}；监测引用 {report.leads.ai_attribution.monitored_citations} 条 / {report.leads.ai_attribution.monitored_citation_urls} 个 URL。来源、渠道、题目明细保留在后台，客户版只展示汇总。</p>
    </section>}

    <footer className="customer-report-footer">
      <div><strong>{payload.brand_name}</strong><span>{payload.contact_text || "如需解读本报告，请联系项目负责人。"}</span></div>
      <div className="customer-report-meta">
        <span>数据冻结于 {formatDateTime(payload.captured_at)}</span>
        <span>数据指纹 {payload.snapshot_hash.slice(0, 12)}</span>
        <span>有效至 {formatDateTime(payload.expires_at)}</span>
      </div>
    </footer>
  </main>;
}
