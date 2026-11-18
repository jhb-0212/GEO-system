"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { PageRecord, SiteDiagnosticsSummary } from "@/lib/workbench/types";

const bucketLabels: Record<string, string> = {
  crawlable_no_visit: "允许爬取但没访问",
  visited_no_citation: "访问了没引用",
  cited_no_mention: "引用了没品牌提及",
  visited_and_cited: "既访问又引用",
};

function yesNo(value: boolean | null) {
  return value === null ? "未检查" : value ? "是" : "否";
}

function pageTone(page: PageRecord) {
  if (page.check_error) return "red" as const;
  if (page.http_status && page.http_status >= 400) return "red" as const;
  if (page.robots_allowed === false || page.in_sitemap === false || page.canonical_ok === false) return "amber" as const;
  if (page.checked_at) return "green" as const;
  return "slate" as const;
}

export function SiteDiagnosticsWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean;
  onNotice: (message: string) => void;
}) {
  const [pages, setPages] = useState<PageRecord[]>([]);
  const [summary, setSummary] = useState<SiteDiagnosticsSummary | null>(null);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.pages(projectId), workbenchClient.siteDiagnostics(projectId)])
      .then(([pageResult, nextSummary]) => {
        if (!active) return;
        setPages(pageResult.data);
        setSummary(nextSummary);
        setError("");
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "官网诊断加载失败"); });
    return () => { active = false; };
  }, [mode, projectId, canRead]);

  async function checkPage(page: PageRecord) {
    setBusyId(page.id);
    try {
      const result = await workbenchClient.checkPage(projectId, page.id);
      setPages((current) => current.map((item) => item.id === page.id ? { ...item, ...result } : item));
      setSummary(await workbenchClient.siteDiagnostics(projectId));
      onNotice(result.check_error ? "检查已执行，但抓取失败，已记录错误" : "页面检查已更新");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "页面检查失败"); }
    finally { setBusyId(""); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">官网诊断请切换到真实接口模式。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容读取权限。</p></Panel>;

  const buckets = summary?.buckets ?? {};
  const metrics: Array<[string, number]> = summary ? [
    ["官网页面", summary.pages_total],
    ["已检查", summary.pages_checked],
    ["robots 拒绝", summary.robots_blocked],
    ["不在 sitemap", summary.not_in_sitemap],
    ["canonical 缺失/异常", summary.canonical_bad],
    ["HTTP 错误", summary.http_error],
    ["依赖 JS", summary.js_dependent],
    ["爬虫事件", summary.crawler_events],
    ["已验证 bot", summary.verified_bot_events],
    ["被爬页面", summary.crawled_pages],
    ["用户访问", summary.traffic_events],
    ["访问会话", summary.visitor_sessions],
    ["带 session 线索", summary.leads_with_session],
  ] : [];

  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>官网 AI 爬虫诊断</h3><p>技术可访问（L1）、实际抓取（L2）、实际引用（L3）分开核对；爬虫访问不计入潜在客户</p></div><Badge tone="blue">事实层</Badge></div>
      <div className="knowledge-list diagnostic-metrics">
        {metrics.map(([label, value]) => <div className="knowledge-item diagnostic-metric" key={String(label)}><span><strong>{value}</strong><small>{label}</small></span></div>)}
      </div>
    </Panel>

    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>诊断四格</h3><p>只做状态归类，不替代人工判断；引用了没品牌提及按页面样本核验结果聚合</p></div></div>
      <div className="knowledge-list diagnostic-metrics">
        {Object.entries(bucketLabels).map(([key, label]) => <div className="knowledge-item diagnostic-metric" key={key}><span><strong>{buckets[key] ?? 0}</strong><small>{label}</small></span></div>)}
        {!summary && <p className="knowledge-empty">暂无汇总</p>}
      </div>
    </Panel>

    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>官网页面检查</h3><p>共 {pages.length} 页；检查结果写回页面台账，失败会保留错误原因</p></div></div>
      <div className="knowledge-list">{pages.map((page) => <div className="knowledge-item" key={page.id}>
        <span>
          <strong>{page.title}</strong>
          <small>{page.url} · {page.page_type} · {page.publish_status}</small>
          <small>
            状态 {page.http_status ?? "—"} · robots {yesNo(page.robots_allowed)} · sitemap {yesNo(page.in_sitemap)} · canonical {yesNo(page.canonical_ok)} · JS 依赖 {yesNo(page.js_dependent)}
          </small>
          {page.check_error && <small className="form-error">检查错误：{page.check_error}</small>}
        </span>
        <span>
          <Badge tone={pageTone(page)}>{page.checked_at ? "已检查" : "未检查"}</Badge>
          {canWrite && <Button variant="secondary" disabled={busyId === page.id} onClick={() => void checkPage(page)}>{busyId === page.id ? "检查中" : "检查"}</Button>}
        </span>
      </div>)}{!pages.length && <p className="knowledge-empty">暂无官网页面，请先在公开站页面台账登记</p>}</div>
      <p className="knowledge-footnote">L2 爬虫日志与 L3 用户访问事件由官网/CDN/埋点导入，导入时只接受已按 IP 反查核验的 verified_bot；本页不自行判定爬虫身份。L1 robots 按 Bytespider 专用组检查，无专用组时回退 * 组，不代表全部 AI 爬虫规则。</p>
    </Panel>
  </div>;
}
