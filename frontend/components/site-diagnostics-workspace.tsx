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

const CHECK_BATCH_SIZE = 5;

type ImportKind = "crawler" | "traffic";

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** 接受 JSON 数组、{events: []} 包装对象和 JSONL；字段校验交给后端 Pydantic。 */
function parseImportEvents(text: string): Record<string, unknown>[] {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("请先粘贴或选择事件 JSON");
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    const lines = trimmed.split(/\r?\n/).filter((line) => line.trim());
    try {
      parsed = lines.map((line) => JSON.parse(line));
    } catch {
      throw new Error("不是合法的 JSON、JSON 数组或 JSONL");
    }
  }
  const events = Array.isArray(parsed)
    ? parsed
    : isRecord(parsed) && Array.isArray(parsed.events)
      ? parsed.events
      : null;
  if (!events) throw new Error("事件必须是 JSON 数组，或包含 events 数组的对象");
  if (!events.length) throw new Error("事件数组不能为空");
  if (!events.every(isRecord)) throw new Error("每个事件都必须是 JSON 对象");
  return events;
}

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

export function SiteDiagnosticsWorkspace({ mode, projectId, canRead, canWrite, canImport, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; canImport: boolean;
  onNotice: (message: string) => void;
}) {
  const [pages, setPages] = useState<PageRecord[]>([]);
  const [summary, setSummary] = useState<SiteDiagnosticsSummary | null>(null);
  const [busyId, setBusyId] = useState("");
  const [bulkChecking, setBulkChecking] = useState(false);
  const [bulkChecked, setBulkChecked] = useState(0);
  const [importKind, setImportKind] = useState<ImportKind>("crawler");
  const [importSource, setImportSource] = useState("");
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
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

  async function refreshSummary() {
    try {
      setSummary(await workbenchClient.siteDiagnostics(projectId));
    } catch (cause) {
      setError(cause instanceof Error ? `汇总刷新失败：${cause.message}` : "汇总刷新失败，请稍后重试");
    }
  }

  async function checkPage(page: PageRecord) {
    setBusyId(page.id);
    try {
      const result = await workbenchClient.checkPage(projectId, page.id);
      setPages((current) => current.map((item) => item.id === page.id ? { ...item, ...result } : item));
      await refreshSummary();
      onNotice(result.check_error ? "检查已执行，但抓取失败，已记录错误" : "页面检查已更新");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "页面检查失败"); }
    finally { setBusyId(""); }
  }

  async function checkAllPages() {
    if (!pages.length || bulkChecking || busyId) return;
    setBulkChecking(true);
    setBulkChecked(0);
    setError("");
    let checked = 0;
    let errors = 0;
    try {
      for (let offset = 0; offset < pages.length; offset += CHECK_BATCH_SIZE) {
        const batch = pages.slice(offset, offset + CHECK_BATCH_SIZE);
        const result = await workbenchClient.checkPages(projectId, batch.map((page) => page.id));
        setPages((current) => current.map((page) => {
          const hit = result.items.find((item) => item.id === page.id);
          return hit ? { ...page, ...hit } : page;
        }));
        checked += result.checked;
        errors += result.errors;
        setBulkChecked(checked);
        await refreshSummary();
      }
      onNotice(errors ? `批量检查完成：${checked} 页，${errors} 页抓取失败已记录` : `批量检查完成：${checked} 页全部成功`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "批量检查失败，已保留已完成的结果"); }
    finally { setBulkChecking(false); }
  }

  async function importEvents() {
    if (!canImport || importing) return;
    setImporting(true);
    setError("");
    try {
      const events = parseImportEvents(importText);
      if (importKind === "crawler") {
        const result = await workbenchClient.importCrawlerEvents(projectId, events, importSource.trim() || undefined);
        setImportText("");
        await refreshSummary();
        onNotice(`已导入 ${result.imported} 条爬虫事件，匹配 ${result.matched_pages} 个官网页面`);
      } else {
        const result = await workbenchClient.importTrafficEvents(projectId, events, importSource.trim() || undefined);
        setImportText("");
        await refreshSummary();
        onNotice(`已导入 ${result.imported} 条访问事件`);
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "日志导入失败"); }
    finally { setImporting(false); }
  }

  async function loadImportFile(file: File | undefined) {
    if (!file) return;
    try {
      setImportText(await file.text());
    } catch { setError("读取文件失败，请直接粘贴 JSON 内容"); }
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
    <Panel className="knowledge-list-panel site-diagnostic-summary">
      <div className="panel-heading"><div><h3>官网 AI 爬虫诊断</h3><p>技术可访问（L1）、实际抓取（L2）、实际引用（L3）分开核对；爬虫访问不计入潜在客户</p></div><Badge tone="blue">事实层</Badge></div>
      <div className="knowledge-list diagnostic-metrics">
        {metrics.map(([label, value]) => <div className="knowledge-item diagnostic-metric" key={String(label)}><span><strong>{value}</strong><small>{label}</small></span></div>)}
      </div>
    </Panel>

    <Panel className="knowledge-list-panel site-diagnostic-summary">
      <div className="panel-heading"><div><h3>诊断四格</h3><p>只做状态归类，不替代人工判断；引用了没品牌提及按页面样本核验结果聚合</p></div></div>
      <div className="knowledge-list diagnostic-metrics">
        {Object.entries(bucketLabels).map(([key, label]) => <div className="knowledge-item diagnostic-metric" key={key}><span><strong>{buckets[key] ?? 0}</strong><small>{label}</small></span></div>)}
        {!summary && <p className="knowledge-empty">暂无汇总</p>}
      </div>
    </Panel>

    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>官网页面检查</h3><p>共 {pages.length} 页；检查结果写回页面台账，失败会保留错误原因</p></div></div>
      {canWrite && <div className="knowledge-actions">
        <Button variant="secondary" disabled={bulkChecking || !!busyId || !pages.length} onClick={() => void checkAllPages()}>
          {bulkChecking ? `批量检查中 ${bulkChecked}/${pages.length}` : bulkChecked ? "重新检查全部" : "检查全部"}
        </Button>
        <span className="knowledge-footnote">按 {CHECK_BATCH_SIZE} 页一批提交，避免单次请求超时；抓取失败只记录到该页，不阻断其他页。</span>
      </div>}
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
          {canWrite && <Button variant="secondary" disabled={busyId === page.id || bulkChecking} onClick={() => void checkPage(page)}>{busyId === page.id ? "检查中" : "检查"}</Button>}
        </span>
      </div>)}{!pages.length && <p className="knowledge-empty">暂无官网页面，请先在公开站页面台账登记</p>}</div>
      <p className="knowledge-footnote">L2 爬虫日志与 L3 用户访问事件由官网/CDN/埋点导入，导入时只接受已按 IP 反查核验的 verified_bot；本页不自行判定爬虫身份。L1 robots 按 Bytespider 专用组检查，无专用组时回退 * 组，不代表全部 AI 爬虫规则。</p>
    </Panel>

    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>L2/L3 日志导入</h3><p>把 CDN/埋点导出的事件按契约导入；L2 写入爬虫事件，L3 写入访问事件，均不改写官网页面台账</p></div><Badge tone={canImport ? "blue" : "slate"}>{canImport ? "可导入" : "无导入权限"}</Badge></div>
      {canImport ? <>
        <div className="knowledge-actions">
          <label className="field"><span className="field-label">导入类型</span>
            <select className="text-input" value={importKind} onChange={(event) => setImportKind(event.target.value as ImportKind)}>
              <option value="crawler">L2 爬虫日志（crawler-events）</option>
              <option value="traffic">L3 访问事件（traffic-events）</option>
            </select>
          </label>
          <label className="field"><span className="field-label">来源标识（可选）</span><input className="text-input" value={importSource} onChange={(event) => setImportSource(event.target.value)} placeholder="如 cdn_csv / ga4_export" /></label>
        </div>
        <label className="field"><span className="field-label">事件 JSON / JSONL</span>
          <textarea className="text-input knowledge-textarea" value={importText} onChange={(event) => setImportText(event.target.value)} placeholder={importKind === "crawler" ? '[{"page_url":"https://www.gdccai.com/a","occurred_at":"2026-11-19T08:00:00+08:00","verified_bot":true}]' : '[{"landing_url":"https://www.gdccai.com/a","occurred_at":"2026-11-19T09:00:00+08:00","visitor_session_id":"s-1"}]'} />
        </label>
        <div className="knowledge-actions">
          <label className="knowledge-footnote">选择文件<input type="file" accept=".json,.jsonl,.txt,application/json,text/plain" onChange={(event) => void loadImportFile(event.target.files?.[0])} /></label>
          <Button disabled={importing || !importText.trim()} onClick={() => void importEvents()}>{importing ? "导入中" : "导入事件"}</Button>
        </div>
        <p className="knowledge-footnote">
          {importKind === "crawler"
            ? "L2 必填 page_url、occurred_at；ua_claimed/source_ip/verified_bot/http_status/bytes 可选。verified_bot 只能来自 IP 反查或 CDN 已验证数据，不能凭 UA 声明填 true。"
            : "L3 必填 landing_url、occurred_at；visitor_session_id/utm_source/utm_campaign/referrer/is_bot 可选。occurred_at 用带时区的 ISO8601。"}
          {" "}字段契约见 <code>docs/site-diagnostics-import.md</code>；也支持 JSONL（一行一个事件）。
        </p>
      </> : <p className="knowledge-empty">当前账号没有 `monitoring.execute` 权限，无法导入 L2/L3 日志。</p>}
    </Panel>
  </div>;
}
