"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelRecord, CitationRecord, SampleDetail, SampleRecord, UnknownDomainRecord } from "@/lib/workbench/types";

type SampleTab = "samples" | "unknown" | "citations";

function readTab(value: string | null): SampleTab {
  return value === "unknown" || value === "citations" ? value : "samples";
}

export function SamplesWorkspace({ mode, projectId, canRead, canReview, canReadChannels, canDownloadEvidence, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canReview: boolean;
  canReadChannels: boolean; canDownloadEvidence: boolean; onNotice: (message: string) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = readTab(searchParams.get("sample_tab"));
  const [samples, setSamples] = useState<SampleRecord[]>([]);
  const [sampleTotal, setSampleTotal] = useState(0);
  const [samplePage, setSamplePage] = useState(1);
  const [selectedSample, setSelectedSample] = useState<SampleDetail | null>(null);
  const [citations, setCitations] = useState<CitationRecord[]>([]);
  const [citationTotal, setCitationTotal] = useState(0);
  const [citationPage, setCitationPage] = useState(1);
  const [selectedCitation, setSelectedCitation] = useState<CitationRecord | null>(null);
  const [unknown, setUnknown] = useState<UnknownDomainRecord[]>([]);
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  const [reviewNote, setReviewNote] = useState("");
  const [citationNote, setCitationNote] = useState("");
  const [channelChoice, setChannelChoice] = useState("keep");
  const [competitorChoice, setCompetitorChoice] = useState("keep");
  const [busy, setBusy] = useState(false);
  const [downloadingEvidenceId, setDownloadingEvidenceId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const loadSamples = useCallback(async () => {
    const result = await workbenchClient.samples(projectId, samplePage);
    setSamples(result.data); setSampleTotal(result.meta?.total ?? result.data.length);
  }, [projectId, samplePage]);
  const loadCitations = useCallback(async () => {
    const result = await workbenchClient.citations(projectId, citationPage);
    setCitations(result.data); setCitationTotal(result.meta?.total ?? result.data.length);
  }, [projectId, citationPage]);
  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([
      workbenchClient.samples(projectId, samplePage), workbenchClient.citations(projectId, citationPage),
      canReadChannels ? workbenchClient.unknownDomains(projectId) : Promise.resolve(null),
      canReadChannels ? workbenchClient.channels(projectId, 1, 100) : Promise.resolve(null),
    ]).then(([s, c, u, ch]) => {
      if (!active) return;
      setSamples(s.data); setSampleTotal(s.meta?.total ?? s.data.length);
      setCitations(c.data); setCitationTotal(c.meta?.total ?? c.data.length);
      setUnknown(u?.data ?? []); setChannels(ch?.data ?? []); setError("");
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "复核数据加载失败"); });
    return () => { active = false; };
  }, [mode, projectId, canRead, canReadChannels, samplePage, citationPage]);

  function selectTab(tab: SampleTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("section", "samples");
    if (projectId && projectId !== "all") params.set("project_id", projectId);
    if (tab === "samples") params.delete("sample_tab");
    else params.set("sample_tab", tab);
    router.push(`/workbench?${params.toString()}`, { scroll: false });
  }

  async function openSample(id: string) {
    try { setSelectedSample(await workbenchClient.sample(projectId, id)); setReviewNote(""); setError(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "样本详情加载失败"); }
  }

  async function reviewSample(result: "hit" | "miss") {
    if (!selectedSample) return; setBusy(true);
    try {
      await workbenchClient.reviewSample(projectId, selectedSample.id, result, reviewNote);
      setSelectedSample(await workbenchClient.sample(projectId, selectedSample.id));
      await loadSamples(); onNotice("样本复核已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "样本复核失败"); }
    finally { setBusy(false); }
  }

  async function downloadEvidence(id: string) {
    if (!canDownloadEvidence) return;
    setDownloadingEvidenceId(id);
    try { await workbenchClient.downloadEvidence(projectId, id); }
    catch (cause) { onNotice(cause instanceof Error ? cause.message : "证据文件下载失败"); }
    finally { setDownloadingEvidenceId(null); }
  }

  function openCitation(row: CitationRecord) {
    setSelectedCitation(row); setCitationNote(row.review_note ?? "");
    setChannelChoice("keep"); setCompetitorChoice("keep");
  }

  async function reviewCitation(status: "manual_confirmed" | "manual_rejected") {
    if (!selectedCitation) return; setBusy(true);
    const input: Record<string, unknown> = { review_status: status };
    if (citationNote !== (selectedCitation.review_note ?? "")) input.review_note = citationNote || null;
    if (channelChoice !== "keep") input.channel_id = channelChoice === "clear" ? null : channelChoice;
    if (competitorChoice !== "keep") input.competitor_id = competitorChoice === "clear" ? null : competitorChoice.trim();
    try {
      const updated = await workbenchClient.reviewCitation(projectId, selectedCitation.citation_id, input);
      setSelectedCitation(updated); setCitations((current) => current.map((item) => item.citation_id === updated.citation_id ? updated : item));
      await loadCitations(); onNotice("引用归属已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "引用复核失败"); }
    finally { setBusy(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">样本与引用复核请切换到真实接口模式。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有监测读取权限。</p></Panel>;
  const tabs: { id: SampleTab; label: string; count: number }[] = [
    { id: "samples", label: "样本回看", count: sampleTotal },
    ...(canReadChannels ? [{ id: "unknown" as SampleTab, label: "待归类域名", count: unknown.length }] : []),
    { id: "citations", label: "引用复核", count: citationTotal },
  ];
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="work-tabs" role="tablist" aria-label="样本与引用视图">
      {tabs.map((tab) => <button type="button" role="tab" aria-selected={activeTab === tab.id} key={tab.id} className={`work-tab ${activeTab === tab.id ? "active" : ""}`} onClick={() => selectTab(tab.id)}>{tab.label}<em>{tab.count}</em></button>)}
    </div>
    {activeTab === "samples" && <>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>样本回看</h3><p>共 {sampleTotal} 条；只有待人工复核且有原始回答的样本可判定</p></div></div>
        <div className="knowledge-list">{samples.map((row) => <button type="button" className="knowledge-item" key={row.id} onClick={() => void openSample(row.id)}><span><strong>样本 {row.id.slice(0, 8)}</strong><small>{row.raw_answer?.slice(0, 100) || row.failure_code || "暂无回答"}</small></span><Badge tone={row.status === "manual_review" ? "amber" : row.status === "failed" ? "red" : "blue"}>{row.status}</Badge></button>)}{!samples.length && <p className="knowledge-empty">暂无样本</p>}</div>
        {sampleTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={samplePage <= 1} onClick={() => setSamplePage(samplePage - 1)}>上一页</Button><span>{samplePage} / {Math.ceil(sampleTotal / 20)}</span><Button variant="secondary" disabled={samplePage * 20 >= sampleTotal} onClick={() => setSamplePage(samplePage + 1)}>下一页</Button></div>}
      </Panel>
      {selectedSample && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>样本详情</h3><p>{selectedSample.id} · {selectedSample.status}</p></div><Button variant="secondary" onClick={() => setSelectedSample(null)}>关闭</Button></div>
        <p className="sample-answer">{selectedSample.raw_answer || "无原始回答"}</p>
        <p className="knowledge-footnote">引用 {selectedSample.citations.length} 条 · 证据文件 {selectedSample.evidence_files.length} 个</p>
        {selectedSample.evidence_files.map((file) => <div className="knowledge-item" key={file.evidence_id}><span><strong>{file.file_type}</strong><small>{file.content_type || "未知类型"} · {file.byte_size == null ? "大小未知" : `${file.byte_size} 字节`}</small></span>{canDownloadEvidence && <Button variant="secondary" disabled={downloadingEvidenceId === file.evidence_id} onClick={() => void downloadEvidence(file.evidence_id)}>{downloadingEvidenceId === file.evidence_id ? "下载中…" : "下载证据"}</Button>}</div>)}
        {!!selectedSample.evidence_files.length && !canDownloadEvidence && <p className="knowledge-footnote">当前账号没有证据文件下载权限。</p>}
        {selectedSample.citations.map((row) => <p className="knowledge-footnote" key={row.citation_id}>{row.domain || "未知域名"} · {row.raw_url}</p>)}
        {canReview && selectedSample.status === "manual_review" && !!selectedSample.raw_answer?.trim() && <div><label className="field"><span className="field-label">复核说明</span><textarea className="text-input knowledge-textarea short" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)}/></label><div className="knowledge-actions"><Button disabled={busy} onClick={() => void reviewSample("hit")}>确认命中</Button><Button variant="secondary" disabled={busy} onClick={() => void reviewSample("miss")}>确认未命中</Button></div></div>}
      </Panel>}
    </>}
    {activeTab === "unknown" && (canReadChannels ? <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>待归类域名</h3><p>按渠道汇总；引用数和样本数用于评估改挂影响</p></div></div><div className="knowledge-list">{unknown.map((row) => <div className="knowledge-item" key={row.channel_id}><span><strong>{row.name}</strong><small>{row.primary_domain || row.code} · 最近采样 {row.last_sampled_at || "暂无"}</small></span><span>引用 {row.citation_count} · 样本 {row.sample_count}</span></div>)}{!unknown.length && <p className="knowledge-empty">暂无待归类域名</p>}</div></Panel> : <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有渠道读取权限，无法查看待归类域名。</p></Panel>)}
    {activeTab === "citations" && <>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>引用复核</h3><p>共 {citationTotal} 条；归属变更只影响当前引用</p></div></div><div className="knowledge-list">{citations.map((row) => <button type="button" className="knowledge-item" key={row.citation_id} onClick={() => openCitation(row)}><span><strong>{row.domain || "未知域名"}</strong><small>{row.raw_url}</small></span><Badge tone={row.review_status === "auto" ? "amber" : "green"}>{row.review_status}</Badge></button>)}{!citations.length && <p className="knowledge-empty">暂无引用</p>}</div>
        {citationTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={citationPage <= 1} onClick={() => setCitationPage(citationPage - 1)}>上一页</Button><span>{citationPage} / {Math.ceil(citationTotal / 20)}</span><Button variant="secondary" disabled={citationPage * 20 >= citationTotal} onClick={() => setCitationPage(citationPage + 1)}>下一页</Button></div>}
      </Panel>
      {selectedCitation && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>引用归属</h3><p>{selectedCitation.raw_url}</p></div><Button variant="secondary" onClick={() => setSelectedCitation(null)}>关闭</Button></div>
        <p className="knowledge-footnote">当前渠道：{selectedCitation.channel_id || "无"} · 当前竞品：{selectedCitation.competitor_id || "无"}</p>
        {canReview ? <form onSubmit={(event) => { event.preventDefault(); void reviewCitation("manual_confirmed"); }}>
          {canReadChannels ? <label className="field"><span className="field-label">渠道归属</span><select className="text-input" value={channelChoice} onChange={(e) => setChannelChoice(e.target.value)}><option value="keep">保留当前归属</option><option value="clear">清空归属</option>{channels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : <label className="field"><span className="field-label">渠道 ID（留空保留，输入 clear 清空）</span><input className="text-input" value={channelChoice === "keep" ? "" : channelChoice} onChange={(e) => setChannelChoice(e.target.value || "keep")}/></label>}
          <label className="field"><span className="field-label">竞品 ID（留空保留，输入 clear 清空）</span><input className="text-input" value={competitorChoice === "keep" ? "" : competitorChoice} onChange={(e) => setCompetitorChoice(e.target.value || "keep")}/></label>
          <label className="field"><span className="field-label">复核备注</span><textarea className="text-input knowledge-textarea short" value={citationNote} onChange={(e) => setCitationNote(e.target.value)}/></label>
          <div className="knowledge-actions"><Button type="submit" disabled={busy}>确认归属</Button><Button variant="secondary" disabled={busy} onClick={() => void reviewCitation("manual_rejected")}>驳回归属</Button></div>
        </form> : <p className="knowledge-empty">当前账号只有查看权限。</p>}
      </Panel>}
    </>}
  </div>;
}
