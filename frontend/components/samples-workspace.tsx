"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, DetailModal, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { workbenchClient, WORKBENCH_PAGE_SIZE } from "@/lib/workbench/client";
import { formatDateTime, formatSerialNo } from "@/lib/workbench/format";
import type { AnswerSnapshotSummary, BrandRelatedPreview, SentimentConsensus, SentimentSampling, SourceDomainsOverview, PageTypeReclassifyResult, ChannelRecord, CitationRecord, CompetitorRecord, MonitoringTaskRecord, SampleDetail, SampleRecord, SourceReviewRecord, UnknownDomainRecord } from "@/lib/workbench/types";

type SampleTab = "samples" | "unknown" | "citations";

/** 后端枚举直出过英文（manual_review / auto），运营看不懂，这里统一中文口径。 */
const sampleStatusNames: Record<string, string> = {
  pending: "待执行", running: "执行中", hit: "命中", miss: "未命中", no_answer_surface: "无答案面", failed: "失败", manual_review: "待人工复核",
};
const taskStatusNames: Record<string, string> = {
  pending: "待执行", running: "执行中", done: "已完成", failed: "失败", uncertain: "不确定", cancelled: "已取消",
};
const taskStatusPriority: Record<string, number> = { failed: 0, uncertain: 1, pending: 2, running: 3, done: 4, cancelled: 5 };
const citationStatusNames: Record<string, string> = {
  auto: "自动判定", manual_confirmed: "人工确认", manual_rejected: "人工驳回",
};
const conversationModeNames: Record<string, string> = {
  stateless: "无状态 API（每次独立请求）", fresh: "新开对话", manual: "人工录入",
};
const manualFailureCodes: { value: string; label: string }[] = [
  { value: "login_blocked", label: "登录阻断" },
  { value: "timeout", label: "超时" },
  { value: "access_blocked", label: "访问受限" },
  { value: "captcha", label: "验证码" },
  { value: "rate_limited", label: "限流" },
  { value: "other", label: "其他" },
];
const sourceCategoryNames: Record<string, string> = {
  brand_owned: "品牌自有", competitor_owned: "竞品自有", social_community: "社交社区",
  content_platform: "内容平台", news_media: "新闻媒体", industry_media: "行业媒体",
  government_institution: "政府机构", education_institution: "教育机构", reference: "百科参考",
  ecommerce: "电商", other: "其他", unknown: "未知",
};
const pageTypeNames: Record<string, string> = {
  homepage: "首页", course_or_product: "课程/产品页", article: "文章", listicle: "榜单/列表",
  how_to: "教程/指南", comparison: "对比页", review: "评测", forum_or_qa: "论坛/问答",
  video: "视频页", case_study: "案例", faq: "FAQ", search_surface: "搜索面",
  admissions: "招生页", recruitment: "招聘页", other: "其他",
};

function readTab(value: string | null): SampleTab {
  return value === "unknown" || value === "citations" ? value : "samples";
}

export function SamplesWorkspace({ mode, projectId, canRead, canReview, canReadChannels, canDownloadEvidence, canCreate, canUploadEvidence, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canReview: boolean;
  canReadChannels: boolean; canDownloadEvidence: boolean; canCreate: boolean; canUploadEvidence: boolean; onNotice: (message: string) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = readTab(searchParams.get("sample_tab"));
  // 任务列表用 history.pushState 跳到手测表单，useSearchParams 不监听该调用，以 location 为准。
  const locationTaskId = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("task_id") : null;
  const requestedTaskId = locationTaskId ?? searchParams.get("task_id") ?? "";
  const [samples, setSamples] = useState<SampleRecord[]>([]);
  const [sampleTotal, setSampleTotal] = useState(0);
  const [samplePage, setSamplePage] = useState(1);
  const [tasks, setTasks] = useState<MonitoringTaskRecord[]>([]);
  const [selectedSample, setSelectedSample] = useState<SampleDetail | null>(null);
  const [citations, setCitations] = useState<CitationRecord[]>([]);
  const [citationTotal, setCitationTotal] = useState(0);
  const [citationPage, setCitationPage] = useState(1);
  const [selectedCitation, setSelectedCitation] = useState<CitationRecord | null>(null);
  const [unknown, setUnknown] = useState<UnknownDomainRecord[]>([]);
  const [sourceReviews, setSourceReviews] = useState<SourceReviewRecord[]>([]);
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, string>>({});
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  // 竞品归属改成下拉：台账接口早就有，之前让人手填 competitor_id 的 UUID，填错就归错竞品。
  const [competitors, setCompetitors] = useState<CompetitorRecord[]>([]);
  const [sampleStatus, setSampleStatus] = useState("");
  const [citationStatus, setCitationStatus] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [citationNote, setCitationNote] = useState("");
  const [citationBrandChoice, setCitationBrandChoice] = useState<"keep" | "true" | "false">("keep");
  const [channelChoice, setChannelChoice] = useState("keep");
  const [competitorChoice, setCompetitorChoice] = useState("keep");
  const [pageTypeChoice, setPageTypeChoice] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [manualTaskId, setManualTaskId] = useState("");
  const [manualAnswer, setManualAnswer] = useState("");
  const [manualKind, setManualKind] = useState("answer");
  const [manualSamplingMode, setManualSamplingMode] = useState("search_on");
  const [manualConversationConfirmed, setManualConversationConfirmed] = useState(false);
  const [manualFailureCode, setManualFailureCode] = useState("");
  const [manualCitationUrls, setManualCitationUrls] = useState("");
  const [manualBrand, setManualBrand] = useState("auto");
  const [manualIdentified, setManualIdentified] = useState("auto");
  const [manualNote, setManualNote] = useState("");
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null);
  const [evidenceType, setEvidenceType] = useState("screenshot");
  const [busy, setBusy] = useState(false);
  const [downloadingEvidenceId, setDownloadingEvidenceId] = useState<string | null>(null);
  const [snapshotInfo, setSnapshotInfo] = useState<AnswerSnapshotSummary | null>(null);
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [pageTypePreview, setPageTypePreview] = useState<PageTypeReclassifyResult | null>(null);
  const [pageTypeMode, setPageTypeMode] = useState<"path" | "content">("path");
  const [brandPreview, setBrandPreview] = useState<BrandRelatedPreview | null>(null);
  const [sentimentQueue, setSentimentQueue] = useState<SentimentSampling | null>(null);
  const [sentimentConsensus, setSentimentConsensus] = useState<SentimentConsensus | null>(null);
  const [domainOverview, setDomainOverview] = useState<SourceDomainsOverview | null>(null);
  const [domainDrafts, setDomainDrafts] = useState<Record<string, string>>({});
  const [labelBusy, setLabelBusy] = useState(false);
  const [error, setError] = useState("");

  const loadSamples = useCallback(async () => {
    const result = await workbenchClient.samples(projectId, samplePage, sampleStatus || undefined);
    setSamples(result.data); setSampleTotal(result.meta?.total ?? result.data.length);
  }, [projectId, samplePage, sampleStatus]);
  const loadCitations = useCallback(async () => {
    const result = await workbenchClient.citations(projectId, citationPage, citationStatus || undefined);
    setCitations(result.data); setCitationTotal(result.meta?.total ?? result.data.length);
  }, [projectId, citationPage, citationStatus]);
  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([
      workbenchClient.samples(projectId, samplePage, sampleStatus || undefined), workbenchClient.citations(projectId, citationPage, citationStatus || undefined),
      canReadChannels ? workbenchClient.unknownDomains(projectId) : Promise.resolve(null),
      canReadChannels ? workbenchClient.sourceReviews(projectId) : Promise.resolve(null),
      canReadChannels ? workbenchClient.channels(projectId, 1, 100) : Promise.resolve(null),
      canCreate ? Promise.all([
        workbenchClient.tasks(projectId, 1, undefined, undefined, 100),
        workbenchClient.tasks(projectId, 1, undefined, "failed"),
        workbenchClient.tasks(projectId, 1, undefined, "uncertain"),
      ]).then(([general, failed, uncertain]) => {
        const merged = [...failed.data, ...uncertain.data, ...general.data];
        return { data: [...new Map(merged.map((task) => [task.id, task])).values()] };
      }) : Promise.resolve(null),
      workbenchClient.competitors(projectId, 1),
    ]).then(([s, c, u, sr, ch, taskList, comp]) => {
      if (!active) return;
      setSamples(s.data); setSampleTotal(s.meta?.total ?? s.data.length);
      setCitations(c.data); setCitationTotal(c.meta?.total ?? c.data.length);
      setUnknown(u?.data ?? []); setSourceReviews(sr?.data ?? []); setChannels(ch?.data ?? []); setTasks(taskList?.data ?? []); setCompetitors(comp.data); setError("");
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "复核数据加载失败"); });
    return () => { active = false; };
  }, [mode, projectId, canRead, canReadChannels, canCreate, samplePage, citationPage, sampleStatus, citationStatus]);

  useEffect(() => {
    if (!canCreate || !requestedTaskId) return;
    if (!tasks.some((task) => task.id === requestedTaskId)) return;
    const timer = window.setTimeout(() => {
      setManualTaskId(requestedTaskId);
      setManualConversationConfirmed(false);
      setManualFailureCode("");
      setManualOpen(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [canCreate, requestedTaskId, tasks]);

  useEffect(() => {
    if (!manualOpen || !requestedTaskId || manualTaskId !== requestedTaskId) return;
    const timer = window.setTimeout(() => {
      document.getElementById("manual-sample-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
      document.getElementById("manual-answer")?.focus({ preventScroll: true });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [manualOpen, requestedTaskId, manualTaskId]);

  function selectTab(tab: SampleTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("section", "samples");
    if (projectId && projectId !== "all") params.set("project_id", projectId);
    if (tab === "samples") params.delete("sample_tab");
    else params.set("sample_tab", tab);
    router.push(`/workbench?${params.toString()}`, { scroll: false });
  }

  async function openSample(id: string) {
    try {
      setSelectedSample(await workbenchClient.sample(projectId, id));
      setReviewNote(""); setError("");
      const listed = await workbenchClient.snapshots(projectId, 1, 50);
      setSnapshotInfo(listed.data.find((row) => row.sample_id === id) ?? null);
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : "样本详情加载失败"); }
  }

  async function previewPageTypes() {
    setBusy(true);
    try {
      const result = await workbenchClient.previewPageTypeReclassify(projectId, 1000, pageTypeMode);
      setPageTypePreview(result);
      onNotice(`预览（${result.mode}）：扫描 ${result.scope.scanned} 条 other，其中 ${result.scope.changed} 条可判出页型（不改库）`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "页型预览失败"); }
    finally { setBusy(false); }
  }

  async function applyPageTypes() {
    setBusy(true);
    try {
      const result = await workbenchClient.applyPageTypeReclassify(projectId, 1000, pageTypeMode);
      setPageTypePreview(null);
      await loadCitations();
      onNotice(`页型重判已写入：改判 ${result.scope.changed} 条（规则版本 ${result.rule_version}）`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "页型重判失败"); }
    finally { setBusy(false); }
  }

  async function backfillTitles() {
    setBusy(true);
    try {
      const result = await workbenchClient.backfillPageTitles(projectId, 100, false);
      onNotice(`标题探测：扫描 ${result.scope.candidates} 条无标题引用，可取回 ${result.scope.titled} 条（不改库）`);
      if (result.scope.titled > 0) {
        const applied = await workbenchClient.backfillPageTitles(projectId, 100, true);
        await loadCitations();
        onNotice(`标题已补回 ${applied.scope.titled} 条，可切到「标题摘要」模式重判页型`);
      }
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "标题补齐失败"); }
    finally { setBusy(false); }
  }

  async function previewBrandRelated() {
    setBusy(true);
    try {
      const result = await workbenchClient.previewBrandRelatedCitations(projectId, 2000);
      setBrandPreview(result);
      onNotice(`品牌相关候选：扫描 ${result.scope.scanned} 条，命中 ${result.scope.candidates} 条（不改库）`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "品牌相关候选预览失败"); }
    finally { setBusy(false); }
  }

  async function applyBrandRelated() {
    setBusy(true);
    try {
      const result = await workbenchClient.applyBrandRelatedCitations(projectId, 2000);
      setBrandPreview(result);
      await loadCitations();
      onNotice(`已标记 ${result.scope.changed} 条为品牌相关（只写 true，不动 false）`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "品牌相关写入失败"); }
    finally { setBusy(false); }
  }

  async function loadDomains() {
    setBusy(true);
    try { setDomainOverview(await workbenchClient.sourceDomains(projectId, 100)); }
    catch (cause) { onNotice(cause instanceof Error ? cause.message : "站点归类预览失败"); }
    finally { setBusy(false); }
  }

  async function fetchDomainEvidence() {
    setBusy(true);
    try {
      const result = await workbenchClient.collectSourceDomainEvidence(projectId, 0);
      await loadDomains();
      onNotice(`抓取站点自证 ${result.fetched} 个，成功 ${result.ok} 个`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "站点证据抓取失败"); }
    finally { setBusy(false); }
  }

  async function classifyDomain(site: string, category: string) {
    setBusy(true);
    try {
      const result = await workbenchClient.classifySourceDomains(projectId, [{ site, category, note: "人工判定（界面）" }]);
      await loadDomains();
      onNotice(`已判定 ${site}，写入 ${result.changed} 条`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "站点判定失败"); }
    finally { setBusy(false); }
  }

  async function applyDomains() {
    setBusy(true);
    try {
      const result = await workbenchClient.applySourceDomains(projectId, 100);
      setDomainOverview(result);
      onNotice(`已按域名身份表写入 ${result.scope.changed} 条`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "站点归类写入失败"); }
    finally { setBusy(false); }
  }

  async function loadSentiment() {
    setBusy(true);
    try {
      const [queue, consensus] = await Promise.all([
        workbenchClient.sentimentSampling(projectId, 1, 12),
        workbenchClient.sentimentConsensus(projectId, 1, 12),
      ]);
      setSentimentQueue(queue);
      setSentimentConsensus(consensus);
      onNotice(`抽样队列 ${queue.sample.length} 条；共识 ${consensus.consensus_total} 条，分歧 ${consensus.disputed} 条`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "情感抽样加载失败"); }
    finally { setBusy(false); }
  }

  async function labelPolarity(citationId: string, polarity: string) {
    setLabelBusy(true);
    try {
      await workbenchClient.labelSentimentPolarity(projectId, citationId, polarity);
      const [queue, consensus] = await Promise.all([
        workbenchClient.sentimentSampling(projectId, 1, 12),
        workbenchClient.sentimentConsensus(projectId, 1, 12),
      ]);
      setSentimentQueue(queue);
      setSentimentConsensus(consensus);
      onNotice("已记录标注；两人同档才算共识，分歧留着仲裁");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "标注失败"); }
    finally { setLabelBusy(false); }
  }

  async function archiveSnapshot() {
    if (!selectedSample) return;
    setSnapshotBusy(true);
    try {
      const saved = await workbenchClient.archiveSampleSnapshot(projectId, selectedSample.id);
      setSnapshotInfo(saved);
      onNotice(saved.created ? "原始回答已存档（不可覆盖）" : "该样本已有快照，未覆盖");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "存档失败"); }
    finally { setSnapshotBusy(false); }
  }

  async function backfillSnapshots() {
    setSnapshotBusy(true);
    try {
      const result = await workbenchClient.captureSnapshots(projectId, 50);
      onNotice(`补档完成：新存 ${result.captured} 条，跳过无回答 ${result.missing_answer} 条`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "补档失败"); }
    finally { setSnapshotBusy(false); }
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

  async function recordSampleReview() {
    if (!selectedSample || !reviewNote.trim()) return; setBusy(true);
    try {
      const result = selectedSample.status === "hit" || selectedSample.status === "miss" ? selectedSample.status : undefined;
      await workbenchClient.recordSampleReview(projectId, selectedSample.id, reviewNote.trim(), result);
      setSelectedSample(await workbenchClient.sample(projectId, selectedSample.id));
      await loadSamples(); onNotice("复核记录已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "复核记录保存失败"); }
    finally { setBusy(false); }
  }

  async function classifySource(review: SourceReviewRecord) {
    const category = sourceDrafts[review.review_id] ?? review.source_category ?? review.suggested_source_category ?? "other";
    setBusy(true);
    try {
      await workbenchClient.classifySourceReview(projectId, review.review_id, category);
      setSourceReviews((rows) => rows.map((row) => row.review_id === review.review_id ? { ...row, status: "classified", source_category: category, classification_source: "manual" } : row));
      onNotice(`已把 ${review.domain} 归为 ${category}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "信源归类失败"); }
    finally { setBusy(false); }
  }

  async function ignoreSource(review: SourceReviewRecord) {
    setBusy(true);
    try {
      await workbenchClient.ignoreSourceReview(projectId, review.review_id);
      setSourceReviews((rows) => rows.map((row) => row.review_id === review.review_id ? { ...row, status: "ignored", reviewed_at: new Date().toISOString() } : row));
      onNotice(`已忽略 ${review.domain}；引用仍保留，后续不再提示审核`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "忽略信源失败"); }
    finally { setBusy(false); }
  }

  async function downloadEvidence(id: string) {
    if (!canDownloadEvidence) return;
    setDownloadingEvidenceId(id);
    try { await workbenchClient.downloadEvidence(projectId, id); }
    catch (cause) { onNotice(cause instanceof Error ? cause.message : "证据文件下载失败"); }
    finally { setDownloadingEvidenceId(null); }
  }

  async function resampleSelected() {
    if (!selectedSample || !canCreate) return;
    if (!window.confirm("重采样会新建一条逻辑样本并调用 AI 平台，可能消耗平台额度。继续？")) return;
    setBusy(true);
    try {
      const result = await workbenchClient.resampleSample(projectId, selectedSample.id);
      onNotice(`已创建重采样任务（sampling_no=${result.sampling_no}），等待 worker 执行`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "重采样失败"); }
    finally { setBusy(false); }
  }

  async function reanalyzeSelected() {
    if (!selectedSample || !canCreate) return;
    setBusy(true);
    try {
      await workbenchClient.reanalyzeSample(projectId, selectedSample.id);
      setSelectedSample(await workbenchClient.sample(projectId, selectedSample.id));
      await loadSamples();
      onNotice("已按本轮测量快照重分析，未调用 AI 平台");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "重分析失败"); }
    finally { setBusy(false); }
  }

  async function createManualSample() {
    if (!manualTaskId || !manualAnswer.trim() || !manualConversationConfirmed) return;
    setBusy(true);
    try {
      const created = await workbenchClient.createSample(projectId, manualTaskId, {
        raw_answer: manualAnswer.trim(),
        answer_kind: manualKind,
        sampling_mode: manualSamplingMode,
        new_conversation_confirmed: true,
        citation_urls: manualCitationUrls.split("\n").map((value) => value.trim()).filter(Boolean),
        brand_mentioned: manualBrand === "auto" ? null : manualBrand === "true",
        brand_identified: manualIdentified === "auto" ? null : manualIdentified === "true",
        note: manualNote.trim() || null,
      });
      const sampleId = String(created.sample_id);
      setManualOpen(false); setManualTaskId(""); setManualAnswer(""); setManualCitationUrls(""); setManualNote("");
      setManualConversationConfirmed(false); setManualFailureCode(""); setManualSamplingMode("search_on");
      await loadSamples();
      await openSample(sampleId);
      onNotice(created.task_status === "done" ? "手测样本已录入，任务已转为完成" : "手测样本已录入，可继续补充证据截图");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "手测样本录入失败"); }
    finally { setBusy(false); }
  }

  async function createManualFailure() {
    if (!manualTaskId || !manualFailureCode) return;
    setBusy(true);
    try {
      const created = await workbenchClient.createManualFailure(projectId, manualTaskId, {
        failure_code: manualFailureCode,
        failure_note: manualNote.trim() || null,
        sampling_mode: manualSamplingMode,
      });
      setManualOpen(false); setManualTaskId(""); setManualAnswer(""); setManualCitationUrls(""); setManualNote("");
      setManualConversationConfirmed(false); setManualFailureCode(""); setManualSamplingMode("search_on");
      await loadSamples();
      await openSample(String(created.sample_id));
      onNotice("已登记失败原因：单独计入失败分桶，不进入有效回答分母");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "手测失败登记失败"); }
    finally { setBusy(false); }
  }

  async function uploadEvidence() {
    if (!selectedSample || !evidenceFile) return;
    setBusy(true);
    try {
      await workbenchClient.uploadEvidence(projectId, selectedSample.id, evidenceFile, evidenceType);
      setEvidenceFile(null);
      setSelectedSample(await workbenchClient.sample(projectId, selectedSample.id));
      onNotice("证据文件已上传");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "证据文件上传失败"); }
    finally { setBusy(false); }
  }

  function openCitation(row: CitationRecord) {
    setSelectedCitation(row); setCitationNote(row.review_note ?? "");
    setCitationBrandChoice("keep");
    setChannelChoice("keep"); setCompetitorChoice("keep"); setPageTypeChoice(row.page_type ?? "");
  }

  async function overridePageType() {
    if (!selectedCitation || !pageTypeChoice) return;
    setBusy(true);
    try {
      const updated = await workbenchClient.overrideCitationPageType(projectId, selectedCitation.citation_id, pageTypeChoice);
      setSelectedCitation(updated);
      setCitations((current) => current.map((item) => item.citation_id === updated.citation_id ? updated : item));
      await loadCitations();
      onNotice("页面类型已人工覆盖");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "页面类型覆盖失败"); }
    finally { setBusy(false); }
  }

  async function reviewCitation(status: "manual_confirmed" | "manual_rejected") {
    if (!selectedCitation) return; setBusy(true);
    const input: Record<string, unknown> = { review_status: status };
    if (citationNote !== (selectedCitation.review_note ?? "")) input.review_note = citationNote || null;
    if (citationBrandChoice !== "keep") input.is_brand_related = citationBrandChoice === "true";
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
  const selectedCitationLinks = selectedSample?.citations ?? [];
  const selectedBrandCitationCount = selectedCitationLinks.filter((row) => row.is_brand_related).length;
  const manualTaskOptions = [...tasks].filter((task) => task.status === "failed" || task.status === "uncertain" || (task.status === "pending" && (task.entry_type === "app_search" || task.entry_type === "web_user"))).sort((a, b) => (taskStatusPriority[a.status] ?? 9) - (taskStatusPriority[b.status] ?? 9));
  const manualSelectedTask = tasks.find((task) => task.id === manualTaskId);
  const canMarkManualFailure = manualSelectedTask?.status === "pending" && (manualSelectedTask.entry_type === "app_search" || manualSelectedTask.entry_type === "web_user");
  const selectedCountedCitationCount = selectedCitationLinks.filter((row) => row.is_brand_related && row.review_status === "manual_confirmed").length;
  const tabs: { id: SampleTab; label: string; count: number }[] = [
    { id: "samples", label: "样本回看", count: sampleTotal },
    ...(canReadChannels ? [{ id: "unknown" as SampleTab, label: "待复核渠道", count: unknown.length }] : []),
    { id: "citations", label: "引用复核", count: citationTotal },
  ];
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <WorkTabs items={tabs} active={activeTab} onChange={selectTab} ariaLabel="样本与引用视图"/>
    {activeTab === "samples" && <>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>样本回看</h3><p>共 {sampleTotal} 条；只有待人工复核且有原始回答的样本可判定；手测样本按“生成回答/检索结果”分开记口径</p></div>{canCreate && <div className="knowledge-actions"><Button variant="secondary" onClick={() => setManualOpen((open) => !open)}>{manualOpen ? "收起手测录入" : "新增手测样本"}</Button><Button variant="secondary" disabled={snapshotBusy} onClick={() => void backfillSnapshots()}>批量补档快照（50 条）</Button></div>}</div>
        <div className="knowledge-actions"><label className="field"><span className="field-label">状态筛选</span><select className="text-input" value={sampleStatus} onChange={(e) => { setSamplePage(1); setSampleStatus(e.target.value); }}><option value="">全部状态</option><option value="manual_review">待人工复核</option><option value="hit">命中</option><option value="miss">未命中</option><option value="no_answer_surface">无答案面</option><option value="failed">失败</option><option value="pending">待执行</option><option value="running">执行中</option></select></label></div>
        <div className="knowledge-list">{samples.map((row) => <button type="button" className="knowledge-item" key={row.id} onClick={() => void openSample(row.id)}><span><strong>样本 #{formatSerialNo(row.serial_no)}</strong><small>{row.answer_excerpt || row.failure_code || "暂无回答"} · 证据 {row.evidence_count ?? 0} 个</small></span><Badge tone={row.status === "manual_review" ? "amber" : row.status === "failed" ? "red" : "blue"}>{sampleStatusNames[row.status] ?? row.status}</Badge></button>)}{!samples.length && <p className="knowledge-empty">暂无样本</p>}</div>
        {sampleTotal > WORKBENCH_PAGE_SIZE && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={samplePage <= 1} onClick={() => { setSelectedSample(null); setSamplePage(samplePage - 1); }}>上一页</Button><span>{samplePage} / {Math.ceil(sampleTotal / WORKBENCH_PAGE_SIZE)}</span><Button variant="secondary" disabled={samplePage * WORKBENCH_PAGE_SIZE >= sampleTotal} onClick={() => { setSelectedSample(null); setSamplePage(samplePage + 1); }}>下一页</Button></div>}
      </Panel>
      {canCreate && manualOpen && <div id="manual-sample-form"><Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>新增手测样本</h3><p>绑定已有监测任务；每题新开对话，失败原因单独登记</p></div><Button variant="secondary" onClick={() => setManualOpen(false)}>关闭</Button></div>
        <label className="field"><span className="field-label">监测任务</span><select className="text-input" value={manualTaskId} onChange={(e) => { setManualTaskId(e.target.value); setManualConversationConfirmed(false); setManualFailureCode(""); }}><option value="">选择任务</option>{manualTaskOptions.map((task) => <option key={task.id} value={task.id}>{task.question_code} · {task.engine_name} · #{task.sampling_no} · {taskStatusNames[task.status] ?? task.status}</option>)}</select></label>
          <p className="knowledge-footnote">失败或不确定的任务可在这里补录手测样本；应用内搜索入口的待处理任务也可直接录入，保存成功后该任务自动转为已完成。失败任务已排在列表前面。</p>
        <div className="knowledge-actions">
          <label className="field"><span className="field-label">联网模式</span><select className="text-input" value={manualSamplingMode} onChange={(e) => setManualSamplingMode(e.target.value)}><option value="search_on">联网开启（search_on）</option><option value="search_off">联网关闭（search_off）</option></select></label>
          <label className="manual-confirm"><input type="checkbox" checked={manualConversationConfirmed} onChange={(e) => setManualConversationConfirmed(e.target.checked)}/> 本题已新开对话，未复用上一题会话</label>
        </div>
        <p className="knowledge-footnote">手测每题必须新开对话；系统会为每条样本写入独立会话 ID。联网模式按实际操作选择，不能默认沿用上一题。</p>
        <label className="field"><span className="field-label">原始回答</span><textarea id="manual-answer" className="text-input knowledge-textarea" required value={manualAnswer} onChange={(e) => setManualAnswer(e.target.value)}/></label>
        <label className="field"><span className="field-label">答案口径</span><select className="text-input" value={manualKind} onChange={(e) => setManualKind(e.target.value)}><option value="answer">生成回答（answer）</option><option value="search_result">检索结果（search_result）</option></select></label>
        <label className="field"><span className="field-label">引用 URL（每行一条，可选）</span><textarea className="text-input knowledge-textarea short" value={manualCitationUrls} onChange={(e) => setManualCitationUrls(e.target.value)}/></label>
        <div className="knowledge-actions">
          <label className="field"><span className="field-label">品牌提及</span><select className="text-input" value={manualBrand} onChange={(e) => setManualBrand(e.target.value)}><option value="auto">自动判定</option><option value="true">提及</option><option value="false">未提及</option></select></label>
          <label className="field"><span className="field-label">品牌可识别</span><select className="text-input" value={manualIdentified} onChange={(e) => setManualIdentified(e.target.value)}><option value="auto">自动判定</option><option value="true">可识别</option><option value="false">不可识别</option></select></label>
        </div>
        <label className="field"><span className="field-label">录入备注</span><input className="text-input" value={manualNote} onChange={(e) => setManualNote(e.target.value)}/></label>
        <div className="knowledge-actions"><Button disabled={busy || !manualTaskId || !manualAnswer.trim() || !manualConversationConfirmed} onClick={() => void createManualSample()}>保存手测样本</Button><span className="knowledge-footnote">未勾选“已新开对话”不能保存；命中口径仍只看品牌是否被点名；地址/电话只记“可识别”</span></div>
        <div className="manual-failure-box">
          <label className="field"><span className="field-label">本次未能采样</span><select className="text-input" value={manualFailureCode} onChange={(e) => setManualFailureCode(e.target.value)}><option value="">选择失败原因</option>{manualFailureCodes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <Button variant="secondary" disabled={busy || !canMarkManualFailure || !manualFailureCode} onClick={() => void createManualFailure()}>标记本次采样失败</Button>
          <span className="knowledge-footnote">{canMarkManualFailure ? "失败样本单独进入失败分桶，不进入有效回答分母，也不按有效未命中计算。" : "只有待执行的网页用户端或应用内任务可登记人工失败。"}</span>
        </div>
      </Panel></div>}
      {selectedSample && <DetailModal eyebrow="SAMPLE DETAIL" title={`样本 #${formatSerialNo(selectedSample.serial_no)}`} subtitle={sampleStatusNames[selectedSample.status] ?? selectedSample.status} onClose={() => setSelectedSample(null)}>
        <p className="knowledge-footnote">题目 {selectedSample.question_code ?? "未知"}{selectedSample.question_version_no ? ` v${selectedSample.question_version_no}` : ""} · {selectedSample.question_title ?? "未关联题目"} · 类型 {selectedSample.question_type ?? "未判定"} / 意图 {selectedSample.question_intent ?? "未判定"}</p>
        <p className="knowledge-footnote">轮次 {selectedSample.round_seq != null ? `#${selectedSample.round_seq}` : "未知"} {selectedSample.round_name ?? ""} · {selectedSample.round_status ?? "未知"} · 快照 {selectedSample.round_snapshot_hash ? selectedSample.round_snapshot_hash.slice(0, 12) : "无"} · 采样 {formatDateTime(selectedSample.sampled_at)}</p>
        <p className="knowledge-footnote">引擎 {selectedSample.engine_name ?? "未知"} / {selectedSample.engine_code ?? ""} · 入口 {selectedSample.entry_name ?? "未知"}（{selectedSample.entry_type ?? "未知"}）· 模型 {selectedSample.model_version ?? selectedSample.engine_model ?? "未记录"} · 搜索模式 {selectedSample.sampling_mode} · 会话 {selectedSample.conversation_id ? selectedSample.conversation_id.slice(0, 12) : "未记录"}（{selectedSample.conversation_mode ? conversationModeNames[selectedSample.conversation_mode] ?? selectedSample.conversation_mode : "未记录"}）</p>
        {selectedSample.question_text && <p className="knowledge-footnote">问题原文：{selectedSample.question_text}</p>}
        <p className="sample-answer">{selectedSample.raw_answer || "无原始回答"}</p>
        <div className="knowledge-actions">
          <span className="knowledge-footnote">原始回答快照：{snapshotInfo ? `已存档 ${formatDateTime(snapshotInfo.captured_at)} · 回答哈希 ${snapshotInfo.answer_hash.slice(0, 12)}${snapshotInfo.answer_drift ? " · 回答已变更（快照保留原版）" : ""}` : "未存档"}</span>
          {canCreate && <Button variant="secondary" disabled={snapshotBusy || !selectedSample.raw_answer?.trim()} onClick={() => void archiveSnapshot()}>存档快照</Button>}
        </div>
        <div className="evidence-stats">
          <span>来源链接 <strong>{selectedCitationLinks.length}</strong></span>
          <span>品牌相关 <strong>{selectedBrandCitationCount}</strong></span>
          <span>计入引用率 <strong>{selectedCountedCitationCount}</strong></span>
          <span>证据文件 <strong>{selectedSample.evidence_files.length}</strong></span>
        </div>
        {selectedCitationLinks.length > 0 && selectedCountedCitationCount === 0 && <p className="knowledge-footnote">当前链接均未同时满足「品牌相关」和「人工确认」，按指标口径引用率计 0；补标品牌相关并复核后才会计入。</p>}
        {selectedSample.brand_match_evidence && <p className="knowledge-footnote">命中依据：{selectedSample.brand_match_kind === "identifier" ? "品牌标识" : "品牌词"}「{selectedSample.brand_match_term}」偏移 {selectedSample.brand_match_offset}{selectedSample.brand_list_rank ? ` · 列表第 ${selectedSample.brand_list_rank} 位` : ""} · 规则 {selectedSample.matcher_version ?? "未知"}。原文：{selectedSample.brand_match_evidence}</p>}
        {selectedSample.brand_identified && !selectedSample.brand_mentioned && selectedSample.brand_match_evidence && <p className="knowledge-footnote">该样本未点名品牌，但给出了可识别标识，按「可识别」单独记录，不计入点名命中率。</p>}
        {selectedSample.brand_mentioned === false && selectedSample.matcher_version && <p className="knowledge-footnote">未命中依据：规则 {selectedSample.matcher_version} 在原文中未找到配置的品牌词；如需改判请人工复核。</p>}
        {canCreate && <div className="knowledge-actions">
          <Button variant="secondary" disabled={busy} onClick={() => void resampleSelected()}>重采样（再抽一次）</Button>
          <Button variant="secondary" disabled={busy || !["hit", "miss", "no_answer_surface"].includes(selectedSample.status)} onClick={() => void reanalyzeSelected()}>重分析（不调用引擎）</Button>
          <span className="knowledge-footnote">重采样会新建逻辑样本并进入统计分母；重分析只按本轮快照重算，不改变样本数。</span>
        </div>}
        {selectedSample.evidence_files.map((file) => <div className="knowledge-item" key={file.evidence_id}><span><strong>{file.file_type}</strong><small>{file.content_type || "未知类型"} · {file.byte_size == null ? "大小未知" : `${file.byte_size} 字节`}</small></span>{canDownloadEvidence && <Button variant="secondary" disabled={downloadingEvidenceId === file.evidence_id} onClick={() => void downloadEvidence(file.evidence_id)}>{downloadingEvidenceId === file.evidence_id ? "下载中…" : "下载证据"}</Button>}</div>)}
        {!!selectedSample.evidence_files.length && !canDownloadEvidence && <p className="knowledge-footnote">当前账号没有证据文件下载权限。</p>}
        {canUploadEvidence && <div className="evidence-box">
          <div className="evidence-box-head"><strong>补充证据</strong><small>截图 / PDF / 文本，单个 ≤20MB</small></div>
          <div className="evidence-box-body">
            <label className="evidence-file">
              <input type="file" accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.md,.csv,.zip" onChange={(e) => setEvidenceFile(e.target.files?.[0] ?? null)}/>
              <span className="evidence-file-cta">选择文件</span>
              <span className={`evidence-file-name${evidenceFile ? "" : " is-empty"}`}>{evidenceFile?.name ?? "尚未选择文件"}</span>
            </label>
            <select className="text-input evidence-type" value={evidenceType} onChange={(e) => setEvidenceType(e.target.value)}><option value="screenshot">截图</option><option value="pdf">PDF</option><option value="attachment">附件</option><option value="other">其他</option></select>
            <Button variant="secondary" disabled={busy || !evidenceFile} onClick={() => void uploadEvidence()}>上传证据</Button>
          </div>
        </div>}
        {selectedSample.citations.length > 0 && <div className="citation-stack">
          <div className="citation-stack-head"><strong>来源链接</strong><small>{selectedSample.citations.length} 条 · 仅「品牌相关 + 人工确认」计入引用率</small></div>
          <div className="citation-rows">
            {selectedSample.citations.map((row) => <div className="citation-row" key={row.citation_id}>
              <span className="citation-domain" title={row.domain || "未知域名"}>{row.domain || "未知域名"}</span>
              <Badge tone={row.is_brand_related ? "blue" : "slate"}>{row.is_brand_related ? "品牌相关" : "非品牌"}</Badge>
              <Badge tone={row.review_status === "manual_confirmed" ? "green" : row.review_status === "manual_rejected" ? "red" : "amber"}>{citationStatusNames[row.review_status] ?? row.review_status}</Badge>
              <div className="citation-source">
                {(row.site_name || row.title) && <span className="citation-source-title">{row.site_name ? `${row.site_name} · ` : ""}{row.title || "未命名来源"}</span>}
                {row.published_at && <small className="citation-snippet">发布时间：{formatDateTime(row.published_at)}</small>}
                {row.snippet && <small className="citation-snippet">{row.snippet}</small>}
                <p className="knowledge-footnote">原始 URL：<a className="citation-url" href={row.raw_url} target="_blank" rel="noreferrer" title={row.raw_url}>{row.raw_url}</a></p>
                <p className="knowledge-footnote">归一化 URL：{row.normalized_url || "未归一化"} · 域名：{row.domain || "未知"} · 渠道 ID：{row.channel_id || "未归属"} · 来源类型：{sourceCategoryNames[row.source_category ?? ""] ?? "未分类"}</p>
              </div>
            </div>)}
          </div>
        </div>}
        {selectedSample.reviewed_at && <p className="knowledge-footnote">复核记录：{formatDateTime(selectedSample.reviewed_at)} · {selectedSample.review_note || "无备注"} · 复核人 {selectedSample.reviewed_by ? selectedSample.reviewed_by.slice(0, 8) : "未记录"}</p>}
        {canReview && selectedSample.status === "manual_review" && !!selectedSample.raw_answer?.trim() && <div><label className="field"><span className="field-label">复核说明</span><textarea className="text-input knowledge-textarea short" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)}/></label><div className="knowledge-actions"><Button disabled={busy} onClick={() => void reviewSample("hit")}>确认命中</Button><Button variant="secondary" disabled={busy} onClick={() => void reviewSample("miss")}>确认未命中</Button></div></div>}
        {canReview && ["hit", "miss", "failed", "no_answer_surface"].includes(selectedSample.status) && !!selectedSample.raw_answer?.trim() && <div><label className="field"><span className="field-label">事后复核说明</span><textarea className="text-input knowledge-textarea short" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)}/></label><div className="knowledge-actions"><Button disabled={busy || !reviewNote.trim()} onClick={() => void recordSampleReview()}>记录复核</Button><span className="knowledge-footnote">只补复核留痕，不改判样本状态，也不改统计分母。</span></div></div>}
      </DetailModal>}
    </>}
    {activeTab === "unknown" && (canReadChannels ? <>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>待复核渠道（发布渠道）</h3><p>按渠道汇总；引用数和样本数用于评估改挂影响。这里只处理发布结果渠道，不按域名自动归因。</p></div></div><div className="knowledge-list">{unknown.map((row) => <div className="knowledge-item" key={row.channel_id}><span><strong>{row.name}</strong><small>{row.primary_domain || row.code} · 最近采样 {row.last_sampled_at || "暂无"}</small></span><span>引用 {row.citation_count} · 样本 {row.sample_count}</span></div>)}{!unknown.length && <p className="knowledge-empty">暂无待复核渠道</p>}</div></Panel>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>未知被引信源（待归类）</h3><p>AI 回答引用到、但不在渠道目录里的域名；归类只影响信源统计，不生成渠道。</p></div></div>
        <div className="knowledge-list">{sourceReviews.map((row) => <div className="knowledge-item" key={row.review_id}><span><strong>{row.domain}</strong><small>{sourceCategoryNames[row.source_category ?? row.suggested_source_category ?? "unknown"] ?? "未分类"} · {row.status === "pending" ? "待审核" : row.status === "classified" ? "已归类" : "已忽略"} · 引用 {row.citation_count} · 样本 {row.sample_count}</small></span>
          {row.status === "pending" && canReview ? <span className="knowledge-actions"><select className="text-input" value={sourceDrafts[row.review_id] ?? row.suggested_source_category ?? "other"} onChange={(e) => setSourceDrafts((drafts) => ({ ...drafts, [row.review_id]: e.target.value }))}>{Object.entries(sourceCategoryNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><Button variant="secondary" disabled={busy} onClick={() => void classifySource(row)}>归类</Button><Button variant="secondary" disabled={busy} onClick={() => void ignoreSource(row)}>忽略</Button></span> : <Badge tone={row.status === "classified" ? "green" : "amber"}>{row.status === "pending" ? "待审核" : row.status === "classified" ? "已归类" : "已忽略"}</Badge>}
        </div>)}{!sourceReviews.length && <p className="knowledge-empty">暂无未知被引信源</p>}</div></Panel>
    </> : <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有渠道读取权限，无法查看待归类域名。</p></Panel>)}
    {activeTab === "citations" && <>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>引用复核</h3><p>共 {citationTotal} 条来源链接；只有「品牌相关 + 人工确认」的才计入引用率</p></div>{canReview && <div className="knowledge-actions"><select className="text-input" value={pageTypeMode} disabled={busy} onChange={(e) => { setPageTypeMode(e.target.value as "path" | "content"); setPageTypePreview(null); }}><option value="path">URL 规则</option><option value="content">标题摘要词表</option></select><Button variant="secondary" disabled={busy} onClick={() => void backfillTitles()}>补齐标题</Button><Button variant="secondary" disabled={busy} onClick={() => void previewPageTypes()}>预览页型重判</Button>{pageTypePreview && <Button disabled={busy || pageTypePreview.scope.changed === 0} onClick={() => void applyPageTypes()}>写入 {pageTypePreview.scope.changed} 条</Button>}<Button variant="secondary" disabled={busy} onClick={() => void previewBrandRelated()}>品牌相关候选</Button>{brandPreview && <Button disabled={busy || brandPreview.scope.candidates === 0} onClick={() => void applyBrandRelated()}>标记 {brandPreview.scope.candidates} 条</Button>}</div>}</div>
        {pageTypePreview && <p className="knowledge-footnote">规则 {pageTypePreview.rule_version}：{Object.entries(pageTypePreview.by_target).map(([target, count]) => `${pageTypeNames[target] ?? target} ${count}`).join(" · ") || "无可判出条目"}；人工改过的页型不会被覆盖。</p>}
        <div className="knowledge-actions"><label className="field"><span className="field-label">复核状态筛选</span><select className="text-input" value={citationStatus} onChange={(e) => { setCitationPage(1); setCitationStatus(e.target.value); }}><option value="">全部状态</option><option value="auto">自动判定（待复核）</option><option value="manual_confirmed">人工确认</option><option value="manual_rejected">人工驳回</option></select></label></div>
        <div className="knowledge-list">{citations.map((row) => <button type="button" className="knowledge-item" key={row.citation_id} onClick={() => openCitation(row)}><span><strong>{row.domain || "未知域名"}</strong><small>{row.raw_url}</small></span><Badge tone={row.review_status === "auto" ? "amber" : "green"}>{citationStatusNames[row.review_status] ?? row.review_status}</Badge></button>)}{!citations.length && <p className="knowledge-empty">暂无引用</p>}</div>
        {brandPreview && <p className="knowledge-footnote">品牌相关候选：扫描 {brandPreview.scope.scanned} 条，命中 {brandPreview.scope.candidates} 条{brandPreview.scope.changed ? `，已写入 ${brandPreview.scope.changed} 条` : ""}；命中依据是标题/摘要/域名出现品牌正式名，只写 true 不写 false。</p>}
        {citationTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={citationPage <= 1} onClick={() => setCitationPage(citationPage - 1)}>上一页</Button><span>{citationPage} / {Math.ceil(citationTotal / 20)}</span><Button variant="secondary" disabled={citationPage * 20 >= citationTotal} onClick={() => setCitationPage(citationPage + 1)}>下一页</Button></div>}
      </Panel>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>来源站点归类</h3><p>按站点判一次、整站生效；身份表只收站点性质公认的域名，其余进人工队列</p></div>{canReview && <div className="knowledge-actions"><Button variant="secondary" disabled={busy} onClick={() => void fetchDomainEvidence()}>抓取站点证据</Button><Button variant="secondary" disabled={busy} onClick={() => void loadDomains()}>预览站点归类</Button>{domainOverview && <Button disabled={busy || domainOverview.scope.suggested_sites === 0} onClick={() => void applyDomains()}>写入身份表 {domainOverview.scope.suggested_sites} 站</Button>}</div>}</div>
        {domainOverview && <p className="knowledge-footnote">共 {domainOverview.scope.sites} 站 / {domainOverview.scope.citations} 条引用：已判 {domainOverview.scope.settled_sites} 站、可一键采纳 {domainOverview.scope.suggested_sites} 站、待人工判 {domainOverview.scope.needs_review_sites} 站；已覆盖 {domainOverview.scope.citations_covered} 条引用。</p>}
        {domainOverview ? <div className="knowledge-list">{domainOverview.domains.filter((row) => row.status !== "settled").map((row) => <div className="knowledge-item" key={row.site}><span><strong>{row.site}</strong><small>{row.citations} 条引用 · 待写 {row.pending} 条 · {row.reason}{row.evidence?.title ? ` · 站内自称：${row.evidence.title}` : ""}{row.evidence?.description ? ` · ${row.evidence.description}` : ""}</small></span>{row.status === "suggested" ? <Badge tone="green">{sourceCategoryNames[row.suggested_category ?? ""] ?? row.suggested_category}（可采纳）</Badge> : canReview ? <span className="knowledge-actions"><select className="text-input" value={domainDrafts[row.site] ?? "news_media"} onChange={(e) => setDomainDrafts((drafts) => ({ ...drafts, [row.site]: e.target.value }))}>{Object.entries(sourceCategoryNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><Button variant="secondary" disabled={busy} onClick={() => void classifyDomain(row.site, domainDrafts[row.site] ?? "news_media")}>判定</Button></span> : <Badge tone="amber">待人工判</Badge>}</div>)}{!domainOverview.domains.length && <p className="knowledge-empty">暂无可归类站点</p>}</div> : <p className="knowledge-empty">点「预览站点归类」查看站点队列；身份不明的站点不会被自动给类别。</p>}
      </Panel>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>情感抽样盲评</h3><p>按「轮次 + 引用 id」稳定抽样；两人同档才算共识，不足 50 条共识不出正向率</p></div>{canReview && <Button variant="secondary" disabled={busy} onClick={() => void loadSentiment()}>载入抽样队列</Button>}</div>
        {sentimentConsensus && <p className="knowledge-footnote">共识 {sentimentConsensus.consensus_total} 条（正向 {sentimentConsensus.counts.positive ?? 0} · 中性 {sentimentConsensus.counts.neutral ?? 0} · 负向 {sentimentConsensus.counts.negative ?? 0}）· 分歧 {sentimentConsensus.disputed} · 未标 {sentimentConsensus.unlabeled} · 正向率 {sentimentConsensus.positive_rate === null ? `未达 ${sentimentConsensus.min_report} 条，不出率` : `${(sentimentConsensus.positive_rate * 100).toFixed(1)}%`}</p>}
        {sentimentQueue ? <div className="knowledge-list">{sentimentQueue.sample.map((row) => <div className="knowledge-item" key={row.citation_id}><span><strong>{row.title || row.domain || "无标题"}</strong><small>{row.domain} · 已标 {row.label_count} 人{row.hints.length ? ` · 负面提示：${row.hints.join("、")}` : ""}</small></span>{canReview ? <span className="knowledge-actions"><Button variant="secondary" disabled={labelBusy} onClick={() => void labelPolarity(row.citation_id, "positive")}>正向</Button><Button variant="secondary" disabled={labelBusy} onClick={() => void labelPolarity(row.citation_id, "neutral")}>中性</Button><Button variant="secondary" disabled={labelBusy} onClick={() => void labelPolarity(row.citation_id, "negative")}>负向</Button></span> : <Badge tone="slate">{row.labels[0]?.polarity ?? "未标"}</Badge>}</div>)}{!sentimentQueue.sample.length && <p className="knowledge-empty">本轮无可抽样本</p>}</div> : <p className="knowledge-empty">点「载入抽样队列」开始本批盲评；负面提示只决定阅读顺序，不进任何比率。</p>}
      </Panel>
      {selectedCitation && <DetailModal eyebrow="CITATION REVIEW" title="引用归属" subtitle={`${selectedCitation.domain || "未知域名"} · ${citationStatusNames[selectedCitation.review_status] ?? selectedCitation.review_status}`} onClose={() => setSelectedCitation(null)}>
        <div className="channel-facts">
          <div className="channel-fact-wide"><span>原始引用 URL</span><strong><a href={selectedCitation.raw_url} target="_blank" rel="noreferrer">{selectedCitation.raw_url}</a></strong></div>
          <div className="channel-fact-wide"><span>归一化 URL</span><strong>{selectedCitation.normalized_url ? <a href={selectedCitation.normalized_url} target="_blank" rel="noreferrer">{selectedCitation.normalized_url}</a> : "未归一化"}</strong></div>
          <div><span>域名</span><strong>{selectedCitation.domain || "未知"}</strong></div>
          <div><span>渠道 ID</span><strong>{selectedCitation.channel_id || "未归属"}</strong></div>
          <div><span>来源类型</span><strong>{sourceCategoryNames[selectedCitation.source_category ?? ""] ?? "未分类"}</strong></div>
          <div><span>引用复核状态</span><strong>{citationStatusNames[selectedCitation.review_status] ?? selectedCitation.review_status}</strong></div>
        </div>
        {(selectedCitation.site_name || selectedCitation.title) && <p className="knowledge-footnote">来源：{selectedCitation.site_name || "未知站点"}{selectedCitation.title ? ` · ${selectedCitation.title}` : ""}</p>}
        {selectedCitation.published_at && <p className="knowledge-footnote">发布时间：{formatDateTime(selectedCitation.published_at)}</p>}
        {selectedCitation.snippet && <p className="knowledge-footnote">摘要：{selectedCitation.snippet}</p>}
        <p className="knowledge-footnote">品牌相关：{selectedCitation.is_brand_related ? "是" : "否"} · 当前渠道名称：{channels.find((item) => item.id === selectedCitation.channel_id)?.name ?? "未匹配"} · 当前竞品：{competitors.find((item) => item.id === selectedCitation.competitor_id)?.name ?? selectedCitation.competitor_id ?? "无"}</p>
        <p className="knowledge-footnote">当前页面类型：{pageTypeNames[selectedCitation.page_type ?? ""] ?? "未分类"} · 分类来源：{selectedCitation.classification_source === "manual" ? "人工覆盖" : selectedCitation.classification_source === "rule" ? "规则判定" : "未分类"}{selectedCitation.classification_rule_version ? ` · 版本 ${selectedCitation.classification_rule_version}` : ""}</p>
        {canReview && <div className="knowledge-actions">
          <label className="field"><span className="field-label">人工覆盖页面类型</span><select className="text-input" value={pageTypeChoice} onChange={(e) => setPageTypeChoice(e.target.value)}><option value="">请选择页面类型</option>{Object.entries(pageTypeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <Button variant="secondary" disabled={busy || !pageTypeChoice} onClick={() => void overridePageType()}>保存页面类型</Button>
          <span className="knowledge-footnote">只改当前这条引用；保存后标记为人工覆盖，自动分类不再改写。</span>
        </div>}
        {canReview ? <form onSubmit={(event) => { event.preventDefault(); void reviewCitation("manual_confirmed"); }}>
          <label className="field"><span className="field-label">品牌相关</span><select className="text-input" value={citationBrandChoice} onChange={(e) => setCitationBrandChoice(e.target.value as "keep" | "true" | "false")}><option value="keep">保留当前判定（{selectedCitation.is_brand_related ? "是" : "否"}）</option><option value="true">品牌相关</option><option value="false">非品牌</option></select></label>
          {canReadChannels ? <label className="field"><span className="field-label">渠道归属</span><select className="text-input" value={channelChoice} onChange={(e) => setChannelChoice(e.target.value)}><option value="keep">保留当前归属</option><option value="clear">清空归属</option>{channels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : <label className="field"><span className="field-label">渠道 ID（留空保留，输入 clear 清空）</span><input className="text-input" value={channelChoice === "keep" ? "" : channelChoice} onChange={(e) => setChannelChoice(e.target.value || "keep")}/></label>}
          <label className="field"><span className="field-label">竞品归属</span><select className="text-input" value={competitorChoice} onChange={(e) => setCompetitorChoice(e.target.value)}><option value="keep">保留当前归属</option><option value="clear">清空归属</option>{selectedCitation.competitor_id && !competitors.some((item) => item.id === selectedCitation.competitor_id) && <option value={selectedCitation.competitor_id}>当前竞品（不在列表首页）</option>}{competitors.map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_active ? "" : "（已停用）"}</option>)}</select></label>
          <label className="field"><span className="field-label">复核备注</span><textarea className="text-input knowledge-textarea short" value={citationNote} onChange={(e) => setCitationNote(e.target.value)}/></label>
          <div className="knowledge-actions"><Button type="submit" disabled={busy}>确认归属</Button><Button variant="secondary" disabled={busy} onClick={() => void reviewCitation("manual_rejected")}>驳回归属</Button></div>
        </form> : <p className="knowledge-empty">当前账号只有查看权限。</p>}
      </DetailModal>}
    </>}
  </div>;
}
