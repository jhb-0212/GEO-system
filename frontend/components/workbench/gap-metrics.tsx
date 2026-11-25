"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type {
  BrandSearchReport,
  CompetitorSourceReport,
  SellingPointRecord,
  SellingPointSummary,
} from "@/lib/workbench/types";

function percent(value: number | null) {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function deltaText(value: number | null, pct: number | null) {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("zh-CN")}${pct === null ? "" : `（${sign}${(pct * 100).toFixed(1)}%）`}`;
}

function splitCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (quoted && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      cells.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current.trim());
  return cells;
}

function parseBrandCsv(text: string) {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length) return { rows: [], error: "CSV 为空" };
  const header = splitCsvLine(lines[0]).map((cell) => cell.replace(/^\uFEFF/, "").toLowerCase());
  const headerMap: Record<string, number> = {};
  header.forEach((cell, index) => {
    const key = cell === "平台" ? "platform" : cell === "日期" ? "date" : cell === "搜索量" ? "search_volume" : cell === "备注" ? "note" : cell;
    headerMap[key] = index;
  });
  if (!["platform", "date", "search_volume"].every((key) => key in headerMap)) {
    return { rows: [], error: "表头需要 platform、date、search_volume（或平台、日期、搜索量）" };
  }
  const rows = [];
  for (const line of lines.slice(1)) {
    const cells = splitCsvLine(line);
    const platform = cells[headerMap.platform] ?? "";
    const date = cells[headerMap.date] ?? "";
    const volume = cells[headerMap.search_volume] ?? "";
    if (!platform || !date || !volume) continue;
    rows.push({
      platform,
      date,
      search_volume: Number(volume.replace(/,/g, "")),
      note: headerMap.note === undefined ? null : cells[headerMap.note] || null,
    });
  }
  return { rows, error: rows.length ? "" : "没有可导入的数据行" };
}

export function SellingPointsPanel({ mode, projectId, canManage, onNotice }: {
  mode: "mock" | "live"; projectId: string; canManage: boolean; onNotice: (message: string) => void;
}) {
  const [summary, setSummary] = useState<SellingPointSummary | null>(null);
  const [points, setPoints] = useState<SellingPointRecord[]>([]);
  const [error, setError] = useState("");
  const [label, setLabel] = useState("");
  const [valueText, setValueText] = useState("");
  const [aliases, setAliases] = useState("");
  const [required, setRequired] = useState(true);
  const [note, setNote] = useState("");
  const [editingId, setEditingId] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    if (mode !== "live" || !projectId || projectId === "all") return;
    try {
      const [nextSummary, nextPoints] = await Promise.all([
        workbenchClient.sellingPointSummary(projectId),
        workbenchClient.sellingPoints(projectId),
      ]);
      setSummary(nextSummary); setPoints(nextPoints); setError("");
    } catch (cause) {
      setSummary(null); setError(cause instanceof Error ? cause.message : "卖点清单加载失败");
    }
  }

  useEffect(() => { void load(); }, [mode, projectId]);

  function resetForm() {
    setEditingId(""); setLabel(""); setValueText(""); setAliases(""); setRequired(true); setNote("");
  }

  function edit(point: SellingPointRecord) {
    setEditingId(point.id);
    setLabel(point.label);
    setValueText(point.value_text ?? "");
    setAliases(point.aliases.join("，"));
    setRequired(point.required);
    setNote(point.note ?? "");
  }

  async function save() {
    if (!label.trim()) return;
    setSaving(true);
    try {
      const payload = {
        label: label.trim(),
        value_text: valueText.trim() || null,
        aliases: aliases.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        required,
        note: note.trim() || null,
      };
      if (editingId) await workbenchClient.updateSellingPoint(projectId, editingId, payload);
      else await workbenchClient.createSellingPoint(projectId, payload);
      onNotice(editingId ? "卖点已更新" : "卖点已新增");
      resetForm();
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "卖点保存失败");
    } finally { setSaving(false); }
  }

  async function toggle(point: SellingPointRecord) {
    setSaving(true);
    try {
      await workbenchClient.updateSellingPoint(projectId, point.id, { is_active: !point.is_active });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "卖点状态更新失败");
    } finally { setSaving(false); }
  }

  return <Panel className="knowledge-list-panel">
    <div className="panel-heading"><div><h3>卖点完整性</h3><p>维护项目卖点清单，逐条核对内容是否提到并说清具体口径</p></div>{summary && <Badge tone={summary.summary.required_coverage !== null && summary.summary.required_coverage < 0.6 ? "amber" : "green"}>必答覆盖 {percent(summary.summary.required_coverage)}</Badge>}</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {mode !== "live" && <p className="knowledge-empty">演示模式不加载卖点清单。</p>}
    {summary && <>
      <div className="stats-cards">
        <div><span>卖点总数</span><strong>{summary.summary.points_total}</strong><small className="stats-card-hint">必答 {summary.summary.required_points}</small></div>
        <div><span>当前母稿</span><strong>{summary.summary.contents_total}</strong><small className="stats-card-hint">草稿不纳入</small></div>
        <div><span>必答覆盖率</span><strong>{percent(summary.summary.required_coverage)}</strong><small className="stats-card-hint">说清口径才算覆盖</small></div>
      </div>
      <div className="table-scroll"><table><thead><tr><th>卖点</th><th>期望口径</th><th>必答</th><th>内容数</th><th>说清</th><th>提到未说清</th><th>未提到</th><th>覆盖率</th></tr></thead><tbody>
        {summary.points.map((item) => <tr key={item.id}>
          <td><strong>{item.label}</strong>{!item.is_active && <p className="muted">已停用</p>}</td>
          <td className="muted">{item.value_text || "—"}</td>
          <td>{item.required ? <Badge tone="blue">必答</Badge> : "选答"}</td>
          <td>{item.content_total}</td><td>{item.covered}</td><td>{item.mentioned}</td><td>{item.missing}</td>
          <td>{percent(item.coverage)}</td>
        </tr>)}
      </tbody></table>{!summary.points.length && <p className="knowledge-empty">还没有卖点，先在下方新增。</p>}</div>
      <p className="viz-footnote">{summary.notes.join(" ")}</p>
    </>}
    {canManage && <div className="adaptation-question g-section-gap">
      <div className="field"><span className="field-label">{editingId ? "编辑卖点" : "新增卖点"}</span></div>
      <div className="adaptation-grid">
        <label className="field"><span className="field-label">卖点名称</span><input className="text-input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="例如：小班教学"/></label>
        <label className="field"><span className="field-label">期望口径</span><input className="text-input" value={valueText} onChange={(e) => setValueText(e.target.value)} placeholder="例如：每班不超过 6 人"/></label>
        <label className="field"><span className="field-label">同义说法</span><input className="text-input" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="用逗号分隔，如：小班,精品班"/></label>
        <label className="field"><span className="field-label">备注</span><input className="text-input" value={note} onChange={(e) => setNote(e.target.value)} /></label>
      </div>
      <div className="knowledge-actions">
        <label className="field-inline"><input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)}/> 必答卖点</label>
        <Button disabled={saving || !label.trim()} onClick={() => void save()}>{saving ? "保存中…" : editingId ? "保存修改" : "新增卖点"}</Button>
        {editingId && <Button variant="secondary" disabled={saving} onClick={resetForm}>取消编辑</Button>}
      </div>
      {points.length > 0 && <div className="knowledge-list g-section-gap-sm">
        {points.map((point) => <div className="knowledge-item" key={point.id}>
          <span><strong>{point.label}{point.required ? " · 必答" : ""}</strong><small>{point.value_text || "只检查是否提到"} · {point.aliases.join("、") || "无同义词"}</small></span>
          <div className="knowledge-actions"><Button variant="secondary" disabled={saving} onClick={() => edit(point)}>编辑</Button><Button variant="secondary" disabled={saving} onClick={() => void toggle(point)}>{point.is_active ? "停用" : "启用"}</Button></div>
        </div>)}
      </div>}
    </div>}
  </Panel>;
}

export function BrandSearchPanel({ mode, projectId, canManage, onNotice }: {
  mode: "mock" | "live"; projectId: string; canManage: boolean; onNotice: (message: string) => void;
}) {
  const [report, setReport] = useState<BrandSearchReport | null>(null);
  const [csv, setCsv] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    if (mode !== "live" || !projectId || projectId === "all") return;
    try { setReport(await workbenchClient.statsBrandSearch(projectId, 90)); setError(""); }
    catch (cause) { setReport(null); setError(cause instanceof Error ? cause.message : "品牌搜索加载失败"); }
  }

  useEffect(() => { void load(); }, [mode, projectId]);

  async function importCsv() {
    const parsed = parseBrandCsv(csv);
    if (parsed.error) { setError(parsed.error); return; }
    setBusy(true);
    try {
      const result = await workbenchClient.importBrandSearch(projectId, parsed.rows, "csv");
      if (result.errors.length) setError(result.errors.slice(0, 3).map((item) => `第 ${item.row} 行：${item.error}`).join("；"));
      else { setError(""); setCsv(""); onNotice(`导入完成：新增 ${result.imported}，更新 ${result.updated}`); }
      if (result.report) setReport(result.report);
      else await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "CSV 导入失败");
    } finally { setBusy(false); }
  }

  async function readFile(file: File) {
    const text = await file.text();
    setCsv(text);
  }

  return <Panel className="knowledge-list-panel">
    <div className="panel-heading"><div><h3>品牌搜索量</h3><p>手工/CSV 导入的搜索量快照与增量；不接指数 API，不把不同平台直接相加</p></div>{report && <Badge tone="blue">{report.platforms.length} 个平台</Badge>}</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {report && <p className="muted">统计窗口：{report.start_date} ~ {report.end_date}（项目时区自然日）</p>}
    {report && <>
      <div className="stats-cards">
        {report.platforms.map((item) => <div key={item.platform}><span>{item.platform}</span><strong>{item.latest_volume.toLocaleString("zh-CN")}</strong><small className="stats-card-hint">{item.latest_date} · 较上次 {deltaText(item.delta, item.delta_pct)}</small></div>)}
        {!report.platforms.length && <div><span>暂无数据</span><strong>—</strong><small className="stats-card-hint">先导入 CSV</small></div>}
      </div>
      {report.platforms.length > 0 && <div className="table-scroll"><table><thead><tr><th>平台</th><th>最新</th><th>上一次</th><th>相邻增量</th><th>窗口增量</th><th>快照数</th></tr></thead><tbody>
        {report.platforms.map((item) => <tr key={item.platform}>
          <td><strong>{item.platform}</strong></td><td>{item.latest_volume.toLocaleString("zh-CN")} <span className="muted">{item.latest_date}</span></td>
          <td>{item.previous_volume === null ? "—" : item.previous_volume.toLocaleString("zh-CN")}</td>
          <td>{deltaText(item.delta, item.delta_pct)}</td><td>{deltaText(item.period_delta, null)}</td><td>{item.points}</td>
        </tr>)}
      </tbody></table></div>}
      <p className="viz-footnote">{report.notes.join(" ")}</p>
    </>}
    {canManage && <div className="adaptation-question g-section-gap">
      <div className="field"><span className="field-label">导入 CSV</span><small className="field-hint">表头：platform,date,search_volume,note；日期 YYYY-MM-DD。同平台同日期覆盖更新。</small></div>
      <div className="knowledge-actions">
        <label className="field-inline">选择 CSV<input type="file" accept=".csv,text/csv" onChange={(e) => { const file = e.target.files?.[0]; if (file) void readFile(file); }}/></label>
      </div>
      <textarea className="text-input knowledge-textarea" value={csv} onChange={(e) => setCsv(e.target.value)} placeholder="也可以直接粘贴 CSV 内容"/>
      <div className="knowledge-actions"><Button disabled={busy || !csv.trim()} onClick={() => void importCsv()}>{busy ? "导入中…" : "导入 CSV"}</Button></div>
    </div>}
  </Panel>;
}

export function CompetitorSourcesPanel({ mode, projectId, onNotice }: {
  mode: "mock" | "live"; projectId: string; onNotice: (message: string) => void;
}) {
  const [report, setReport] = useState<CompetitorSourceReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "live" || !projectId || projectId === "all") return;
    workbenchClient.statsCompetitorSources(projectId, 90, 20)
      .then((rows) => { setReport(rows); setError(""); })
      .catch((cause) => { setReport(null); setError(cause instanceof Error ? cause.message : "竞品信源加载失败"); });
  }, [mode, projectId]);

  return <Panel className="knowledge-list-panel">
    <div className="panel-heading"><div><h3>竞品信源质量</h3><p>按竞品拆出已复核引用站点与 T0–T3 结构；不做合成分</p></div>{report && <Badge tone="blue">{report.summary.competitors} 个竞品</Badge>}</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {report && <p className="muted">统计窗口：{report.start_date} ~ {report.end_date}（项目时区自然日）</p>}
    {report && <>
      <div className="stats-cards">
        <div><span>竞品数</span><strong>{report.summary.competitors}</strong></div>
        <div><span>竞品引用条数</span><strong>{report.summary.citations}</strong></div>
        <div><span>有 T0/T1 信源的竞品</span><strong>{report.summary.competitors_with_t0_t1}</strong></div>
        <div><span>平均高权重占比</span><strong>{percent(report.summary.average_high_quality_share)}</strong></div>
      </div>
      <div className="table-scroll"><table><thead><tr><th>竞品</th><th>引用</th><th>样本</th><th>T0</th><th>T1</th><th>T2</th><th>T3</th><th>高权重占比</th><th>Top 域名</th></tr></thead><tbody>
        {report.competitors.map((item) => <tr key={item.id}>
          <td><strong>{item.name}</strong><p className="muted">{item.domain_count} 个站</p></td>
          <td>{item.citations}</td><td>{item.samples}</td>
          <td>{item.tier_counts.T0 ?? 0}</td><td>{item.tier_counts.T1 ?? 0}</td><td>{item.tier_counts.T2 ?? 0}</td><td>{item.tier_counts.T3 ?? 0}</td>
          <td><Badge tone={item.high_quality_share >= 0.5 ? "green" : "slate"}>{percent(item.high_quality_share)}</Badge></td>
          <td>{item.top_domains.map((domain) => <span className="muted" key={domain.domain}>{domain.domain}（{domain.tier}，{domain.citations}）<br/></span>)}</td>
        </tr>)}
      </tbody></table>{!report.competitors.length && <p className="knowledge-empty">窗口内没有已复核的竞品引用。</p>}</div>
      <p className="viz-footnote">{report.notes.join(" ")}</p>
    </>}
    {mode !== "live" && <p className="knowledge-empty">演示模式不加载竞品信源。</p>}
  </Panel>;
}
