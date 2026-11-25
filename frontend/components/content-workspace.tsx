"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, DetailModal, Icon, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { TablePager } from "./table-pager";
import { workbenchClient, WORKBENCH_PAGE_SIZE } from "@/lib/workbench/client";
import { formatDateTime, formatPersonName } from "@/lib/workbench/format";
import type { ChannelRecord, CitationAnswerOption, ContentExportPackage, ContentGeoScoreRecord, ContentQualityReport, ContentReviewRecord, ContentVersionDetail, ContentVersionRecord, FactRecord, QuestionRecord } from "@/lib/workbench/types";

type ContentTab = "versions" | "create";

const CONTENT_FORMAT_LABELS: Record<string, string> = {
  definition: "定义",
  tutorial: "教程",
  comparison: "对比",
  listicle: "清单",
  faq: "FAQ",
  case_study: "案例",
};

function contentFormatLabel(value?: string | null) {
  return value ? CONTENT_FORMAT_LABELS[value] ?? value : "";
}

const CONTENT_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  pending_review: "待审核",
  approved: "已通过",
  rejected: "已驳回",
  scheduled: "已排期",
  pending_publish: "待发布",
  published: "已发布",
  needs_attention: "需处理",
  archived: "已归档",
};

function contentStatusLabel(item: ContentVersionRecord | string): string {
  if (typeof item === "string") return CONTENT_STATUS_LABELS[item] ?? item;
  return item.status_label || CONTENT_STATUS_LABELS[item.status] || item.status;
}

function readTab(value: string | null): ContentTab {
  return value === "create" ? "create" : "versions";
}

const REVIEW_DECISION_LABELS: Record<string, string> = {
  approved: "通过",
  rejected: "驳回",
};

const FACT_STATUS_LABELS: Record<string, string> = {
  approved: "已批准",
  pending: "待批准",
  expired: "已过期",
  revoked: "已撤销",
};

function reviewDecisionLabel(decision: string) {
  return REVIEW_DECISION_LABELS[decision] ?? decision;
}

function factStatusLabel(status: string) {
  return FACT_STATUS_LABELS[status] ?? status;
}

export function ContentWorkspace({ mode, projectId, canRead, canWrite, canReview, onNotice, demoItems }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; canReview: boolean;
  onNotice: (message: string) => void;
  /** 演示数据：形状与 content-versions 接口一致，让 mock 与 live 共用同一套渲染。 */
  demoItems?: ContentVersionRecord[];
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = readTab(searchParams.get("content_tab"));
  const [status, setStatus] = useState("");
  const [contentTypeFilter, setContentTypeFilter] = useState("");
  const [withinDays, setWithinDays] = useState("");
  const [items, setItems] = useState<ContentVersionRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ContentVersionDetail | null>(null);
  const [history, setHistory] = useState<ContentReviewRecord[]>([]);
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  const [questions, setQuestions] = useState<QuestionRecord[]>([]);
  const [facts, setFacts] = useState<FactRecord[]>([]);
  const [linksOpen, setLinksOpen] = useState(false);
  const [linkQuestionIds, setLinkQuestionIds] = useState<string[]>([]);
  const [linkCitationIds, setLinkCitationIds] = useState<string[]>([]);
  const [linkFactIds, setLinkFactIds] = useState<string[]>([]);
  const [citationOptions, setCitationOptions] = useState<CitationAnswerOption[]>([]);
  const [citationQuery, setCitationQuery] = useState("");
  const [citationLoading, setCitationLoading] = useState(false);
  const [citationError, setCitationError] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("channel");
  const [contentFormat, setContentFormat] = useState("");
  const [channelId, setChannelId] = useState("");
  const [parentId, setParentId] = useState("");
  const [body, setBody] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [createdItemId, setCreatedItemId] = useState("");
  const [comment, setComment] = useState("");
  const [bundle, setBundle] = useState<ContentExportPackage | null>(null);
  // 提交前置质检：与后端提交判定同一套规则，草稿/驳回状态下自查用
  const [quality, setQuality] = useState<ContentQualityReport | null>(null);
  // GEO 内容评分：只说明准备度，不阻断提交，也不承诺平台收录或排名
  const [geoScore, setGeoScore] = useState<ContentGeoScoreRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const result = await workbenchClient.contentVersions(projectId, status, page, contentTypeFilter || undefined, withinDays ? Number(withinDays) : undefined);
    setItems(result.data); setTotal(result.meta?.total ?? result.data.length);
  }, [projectId, status, page, contentTypeFilter, withinDays]);
  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([
      workbenchClient.contentVersions(projectId, status, page, contentTypeFilter || undefined, withinDays ? Number(withinDays) : undefined),
      canWrite ? workbenchClient.channels(projectId, 1, 100) : Promise.resolve(null),
      canWrite ? workbenchClient.questions(projectId, 1, "active") : Promise.resolve(null),
      canWrite ? workbenchClient.facts(projectId, undefined, undefined, 1) : Promise.resolve(null),
    ])
      .then(([result, channelList, questionList, factList]) => { if (!active) return; setItems(result.data); setTotal(result.meta?.total ?? result.data.length); setChannels(channelList?.data ?? []); setQuestions(questionList?.data ?? []); setFacts(factList?.data ?? []); setError(""); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "内容列表加载失败"); });
    return () => { active = false; };
  }, [mode, canRead, canWrite, projectId, status, page, contentTypeFilter, withinDays]);

  useEffect(() => {
    if (!linksOpen || !selected || mode !== "live" || !canWrite || projectId === "all") return;
    let active = true;
    workbenchClient.citationAnswerOptions(projectId)
      .then((result) => { if (active) setCitationOptions(result.data); })
      .catch((cause) => { if (active) setCitationError(cause instanceof Error ? cause.message : "来源选项加载失败"); })
      .finally(() => { if (active) setCitationLoading(false); });
    return () => { active = false; };
  }, [linksOpen, selected?.version_id, mode, canWrite, projectId, selected]);

  async function openVersion(id: string) {
    if (mode === "mock") {
      const record = (demoItems ?? []).find((item) => item.version_id === id);
      if (!record) return;
      setSelected({ ...record, body: "演示模式只展示审核面板结构；接入真实接口后这里显示正文与审批记录。", content_hash: "demo", change_note: null, question_ids: [], citation_ids: [], fact_ids: [], fact_links: [] });
      setHistory([]); setComment(""); setBundle(null); setError(""); setQuality(null); setGeoScore(null);
      setLinksOpen(false); setLinkQuestionIds([]); setLinkCitationIds([]); setLinkFactIds([]);
      setCitationOptions([]); setCitationQuery(""); setCitationError("");
      return;
    }
    try {
      const [detail, reviews, qualityReport, scoreReport] = await Promise.all([
        workbenchClient.contentVersion(projectId, id),
        workbenchClient.contentReviews(projectId, id),
        workbenchClient.contentQuality(projectId, id).catch(() => null),
        workbenchClient.contentGeoScore(projectId, id).catch(() => null),
      ]);
      setSelected(detail); setHistory(reviews.data); setQuality(qualityReport); setGeoScore(scoreReport); setComment(""); setBundle(null); setError("");
      setLinksOpen(false); setLinkQuestionIds(detail.question_ids ?? []); setLinkCitationIds(detail.citation_ids ?? []); setLinkFactIds(detail.fact_ids ?? []);
      setCitationQuery(""); setCitationError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "内容详情加载失败"); }
  }

  async function exportBundle() {
    if (!selected) return; setBusy(true);
    try {
      const data = await workbenchClient.contentExport(projectId, selected.version_id);
      setBundle(data); setError(""); onNotice("发布素材已准备，可复制到公司官网后台使用");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "发布素材生成失败"); }
    finally { setBusy(false); }
  }

  async function copyBundle(label: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      onNotice(`${label}已复制到剪贴板`);
    } catch { setError(`${label}复制失败，请手动选中下方文本复制`); }
  }

  async function createContent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!title.trim() || !body.trim()) return; setBusy(true);
    try {
      let itemId = createdItemId;
      if (!itemId) {
        const created = await workbenchClient.contentAction(projectId, "content-item", {
          title: title.trim(), kind, content_type: kind === "master" ? contentFormat || null : null,
          channel_id: kind === "channel" ? channelId || null : null,
          parent_id: parentId || null,
        });
        itemId = String(created.item_id);
        setCreatedItemId(itemId);
      }
      await workbenchClient.contentAction(projectId, "content-version-create", { body: body.trim(), change_note: changeNote || null }, itemId);
      setCreatedItemId(""); setTitle(""); setBody(""); setChangeNote(""); setParentId(""); setContentFormat("");
      setStatus("draft"); setContentTypeFilter(""); setWithinDays(""); setPage(1); setSelected(null);
      try {
        const result = await workbenchClient.contentVersions(projectId, "draft", 1);
        setItems(result.data); setTotal(result.meta?.total ?? result.data.length); setError("");
      } catch { setError("草稿已保存，但列表刷新失败；请重新打开页面查看"); }
      onNotice("草稿已保存，可在草稿列表提交审核");
      selectTab("versions");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "内容保存失败；可用当前表单重试"); }
    finally { setBusy(false); }
  }

  async function submit() {
    if (!selected) return; setBusy(true);
    try {
      await workbenchClient.contentAction(projectId, "content-submit", {}, selected.version_id);
      setSelected(null); await refresh(); onNotice("内容已提交审核");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "提交审核失败"); }
    finally { setBusy(false); }
  }

  async function review(decision: "approved" | "rejected") {
    if (!selected) return; setBusy(true);
    try {
      await workbenchClient.contentAction(projectId, "content-review", { decision, comment: comment || null }, selected.version_id);
      setSelected(null); await refresh(); onNotice(decision === "approved" ? "版本已审批通过" : "版本已驳回");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "审批失败"); }
    finally { setBusy(false); }
  }

  async function saveLinks(confirmFactRevisions = false) {
    if (!selected) return; setBusy(true);
    try {
      const links = await workbenchClient.updateContentLinks(projectId, selected.version_id, {
        question_ids: linkQuestionIds,
        citation_ids: linkCitationIds,
        fact_ids: linkFactIds,
        confirm_fact_revisions: confirmFactRevisions,
      });
      setSelected({ ...selected, question_ids: links.question_ids, citation_ids: links.citation_ids, fact_ids: links.fact_ids, fact_links: links.fact_links });
      setLinkCitationIds(links.citation_ids);
      setLinkFactIds(links.fact_ids);
      setLinksOpen(false);
      setGeoScore(await workbenchClient.contentGeoScore(projectId, selected.version_id).catch(() => geoScore));
      onNotice(confirmFactRevisions ? "事实版本已重新确认" : "题目、证据与事实关联已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "关联保存失败"); }
    finally { setBusy(false); }
  }

  async function changeStatus(status: "pending_publish" | "needs_attention") {
    if (!selected) return; setBusy(true);
    try {
      await workbenchClient.changeContentStatus(projectId, selected.version_id, status);
      await openVersion(selected.version_id);
      await refresh();
      onNotice(status === "pending_publish" ? "版本已标记待发布" : "版本已标记需处理");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "状态切换失败"); }
    finally { setBusy(false); }
  }

  function selectTab(tab: ContentTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("section", "reviews");
    if (projectId && projectId !== "all") params.set("project_id", projectId);
    if (tab === "versions") params.delete("content_tab");
    else params.set("content_tab", tab);
    router.push(`/workbench?${params.toString()}`, { scroll: false });
  }

  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容查看权限。</p></Panel>;
  const demo = mode === "mock";
  // 演示数据与真实数据共用同一个状态过滤：否则「切到已通过仍显示全部」，
  // 演示得出的结论与真实行为不一致。
  const list = (demo ? demoItems ?? [] : items)
    .filter((item) => !status || item.status === status)
    .filter((item) => !contentTypeFilter || item.content_type === contentTypeFilter)
    .filter((item) => {
      if (!withinDays) return true;
      const date = item.submitted_at;
      return date ? Date.now() - new Date(date).getTime() <= Number(withinDays) * 86400000 : false;
    });
  // 待处理优先：进页面先看到需要动作的版本，已发布/归档留在下面，不另开窗口滚动。
  const queueRank: Record<string, number> = { needs_attention: 0, pending_review: 1, pending_publish: 2, draft: 3, rejected: 4, approved: 5, published: 6, archived: 7 };
  const queueList = [...list].sort((left, right) => (queueRank[left.status] ?? 9) - (queueRank[right.status] ?? 9));
  const listTotal = demo ? list.length : total;
  const tabs: { id: ContentTab; label: string; count?: number }[] = [
    { id: "versions", label: "内容版本", count: listTotal },
    ...(canWrite ? [{ id: "create" as ContentTab, label: "新建内容" }] : []),
  ];
  const staleFacts = selected?.fact_links.filter((link) => link.stale) ?? [];
  const revisedFacts = staleFacts.filter((link) => link.warning?.includes("已修订") ?? false);
  const selectedCitationOption = citationOptions.find((option) => option.citation_ids.some((id) => linkCitationIds.includes(id)));
  const normalizedCitationQuery = citationQuery.trim().toLowerCase();
  const filteredCitationOptions = citationOptions.filter((option) => {
    if (!normalizedCitationQuery) return true;
    return [
      option.question_title,
      option.question_text,
      option.engine_name,
      option.entry_name,
      option.answer_excerpt ?? "",
      option.domains.join(" "),
    ].some((value) => value.toLowerCase().includes(normalizedCitationQuery));
  });
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    {demo && <p className="knowledge-footnote" role="note">演示数据：这里展示审核流程；提交审核与审批在正式数据中生效。</p>}
    <WorkTabs items={tabs} active={canWrite ? activeTab : "versions"} onChange={selectTab} ariaLabel="内容审核视图"/>
    {(activeTab === "versions" || !canWrite) && <>
      <Panel className="knowledge-list-panel content-queue-panel"><div className="panel-heading"><div><h3>内容版本</h3><p>优先显示需处理、待审核与待发布版本；点开一条查看正文和审批记录</p></div></div>
        <div className="queue-filter-row">
          <label className="queue-filter"><span>类型</span><select value={contentTypeFilter} onChange={(e) => { setContentTypeFilter(e.target.value); setPage(1); setSelected(null); }}><option value="">全部类型</option>{Object.entries(CONTENT_FORMAT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="queue-filter"><span>状态</span><select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); setSelected(null); }}><option value="">全部状态</option><option value="pending_review">待审核</option><option value="draft">草稿</option><option value="approved">已通过</option><option value="pending_publish">待发布</option><option value="published">已发布</option><option value="needs_attention">需处理</option><option value="rejected">已驳回</option><option value="archived">已归档</option></select></label>
          <label className="queue-filter"><span>时效</span><select value={withinDays} onChange={(e) => { setWithinDays(e.target.value); setPage(1); setSelected(null); }}><option value="">全部时间</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option></select></label>
        </div>
        <div className="knowledge-list content-review-list" key={page}>{queueList.map((item) => <button className="knowledge-item" type="button" key={item.version_id} onClick={() => void openVersion(item.version_id)}><span><strong>{item.title} · v{item.version_no}</strong><small>{contentFormatLabel(item.content_type) ? `${contentFormatLabel(item.content_type)} · ` : ""}{formatPersonName(item.author_name) || "未知作者"} · {item.submitted_at ? formatDateTime(item.submitted_at) : "尚未提交"}</small></span><Badge tone={item.status === "published" || item.status === "approved" ? "green" : item.status === "rejected" || item.status === "needs_attention" ? "red" : "amber"}>{contentStatusLabel(item.status)}</Badge></button>)}{!list.length && <p className="knowledge-empty">{status || contentTypeFilter || withinDays ? "当前筛选没有内容版本，清空筛选查看全部。" : "当前状态暂无版本"}</p>}</div>
        {!demo && <TablePager page={page} total={total} pageSize={WORKBENCH_PAGE_SIZE} loading={busy} onChange={setPage}/>}
      </Panel>
      {selected && <DetailModal eyebrow="内容详情" title={selected.title} subtitle={`第 ${selected.version_no} 版 · ${selected.kind === "channel" ? "渠道稿" : selected.kind === "master" ? "母稿" : selected.kind}${contentFormatLabel(selected.content_type) ? ` · ${contentFormatLabel(selected.content_type)}` : ""} · ${contentStatusLabel(selected.status)}`} onClose={() => setSelected(null)}>
        {!demo && <div className="content-action-bar">
          {canWrite && ["draft", "rejected"].includes(selected.status) && <Button disabled={busy} onClick={() => void submit()}>提交审核</Button>}
          {canWrite && ["approved", "needs_attention"].includes(selected.status) && <Button disabled={busy} onClick={() => void changeStatus("pending_publish")}>标记待发布</Button>}
          {canWrite && ["approved", "pending_publish", "published"].includes(selected.status) && <Button variant="secondary" disabled={busy} onClick={() => void changeStatus("needs_attention")}>标记需处理</Button>}
          <span className="knowledge-footnote">已发布由发布记录自动结案，不能手动修改</span>
        </div>}
        {!demo && canReview && selected.status === "pending_review" && <div className="content-review-box">
          <label className="field"><span className="field-label">审批意见</span><textarea className="text-input knowledge-textarea short" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="可填写通过或驳回的原因"/></label>
          <div className="knowledge-actions"><Button disabled={busy} onClick={() => void review("approved")}>通过</Button><Button variant="secondary" disabled={busy} onClick={() => void review("rejected")}>驳回</Button></div>
        </div>}
        {staleFacts.length > 0 && <p className="form-error" role="alert">有 {staleFacts.length} 条关联事实需要处理，处理后才能通过：{staleFacts.map((link) => `${link.fact_key}（${link.warning}）`).join("；")}</p>}
        {!demo && quality && <div className={`quality-box${quality.ok ? "" : " quality-box-bad"}`}>
          <div className="quality-head">
            <strong>提交前置质检</strong>
            <Badge tone={quality.ok ? "green" : "red"}>{quality.ok ? (quality.warnings.length ? `${quality.warnings.length} 条提示` : "无问题") : `${quality.counts.blockers} 项需处理`}</Badge>
          </div>
          {quality.blockers.length > 0 && <ul className="dist-checks">
            {quality.blockers.map((item, index) => <li key={`b-${item.key}-${index}`}><span className="dist-check-fail">需处理</span><span className="dist-check-label">{item.label}</span><span className="dist-check-detail">{item.detail}</span></li>)}
          </ul>}
          {quality.warnings.length > 0 && <ul className="dist-checks">
            {quality.warnings.map((item, index) => <li key={`w-${item.key}-${index}`}><span className="dist-check-warn">提示</span><span className="dist-check-label">{item.label}</span><span className="dist-check-detail">{item.detail}</span></li>)}
          </ul>}
          {quality.ok && quality.warnings.length === 0 && <p className="knowledge-footnote">未命中绝对化承诺、占位、未登记号码等问题，可直接提交审核。</p>}
        </div>}
        {!demo && geoScore && <div className="geo-score-box">
          <div className="geo-score-head">
            <div>
              <strong>GEO 内容评分</strong>
              <small>v2 规则 · 六项分项，不合成总分</small>
            </div>
            <span className={`geo-score-attention${(geoScore.attention_count ?? 0) ? " has-low" : ""}`}>{(geoScore.attention_count ?? 0) ? `${geoScore.attention_count} 项低于 70` : "六项均无明显缺口"}</span>
          </div>
          {geoScore.selling_points && <div className="geo-completeness">
            <div className="geo-completeness-head">
              <strong>卖点完整性</strong>
              <span className={`geo-completeness-state is-${geoScore.selling_points.status === "missing" ? "missing" : geoScore.selling_points.status === "ok" ? "ok" : "partial"}`}>{geoScore.selling_points.status_label}</span>
              <small>说清 {geoScore.selling_points.covered}/{geoScore.selling_points.points_total} · 必答 {geoScore.selling_points.required_covered}/{geoScore.selling_points.required_total}</small>
            </div>
            {geoScore.selling_points.points.length > 0 && <ul className="geo-completeness-list">
              {geoScore.selling_points.points.map((item) => <li key={item.id} className={`is-${item.status}`}>
                <span>{item.status_label}</span>
                <strong>{item.label}{item.required ? " · 必答" : ""}</strong>
                <small>{item.value_text ? `期望口径：${item.value_text}` : "未配置具体口径，只检查是否提到"}</small>
              </li>)}
            </ul>}
            <p className="geo-completeness-note">{geoScore.selling_points.notes.join(" ")}</p>
          </div>}
          {geoScore.completeness && <div className="geo-completeness">
            <div className="geo-completeness-head">
              <strong>内容完整性</strong>
              <span className={`geo-completeness-state is-${geoScore.completeness.status}`}>{{
                ok: "问句均已答到点",
                partial: "部分问句只命中关键词",
                missing: "未答到点",
                no_questions: "未关联问句",
              }[geoScore.completeness.status]}</span>
              <small>答到点 {geoScore.completeness.questions_answered}/{geoScore.completeness.questions_total} · 关联事实已用 {geoScore.completeness.facts_used}/{geoScore.completeness.facts_total}</small>
            </div>
            {geoScore.completeness.questions.length > 0 && <ul className="geo-completeness-list">
              {geoScore.completeness.questions.map((item, index) => <li key={`${item.title}-${index}`} className={`is-${item.status}`}>
                <span>{item.status === "covered" ? "已答" : item.status === "keyword_only" ? "只命中关键词" : "未回应"}</span>
                <strong>{item.title}</strong>
                <small>{item.detail}</small>
              </li>)}
            </ul>}
            {geoScore.completeness.facts_unused.length > 0 && <details className="geo-completeness-facts">
              <summary>有 {geoScore.completeness.facts_unused.length} 条关联事实未在正文出现（不等于内容错误）</summary>
              <ul>{geoScore.completeness.facts_unused.map((item, index) => <li key={`${item.fact_key}-${index}`}><strong>{item.fact_key ?? item.fact_type ?? "事实"}</strong><span>{item.fact_value}</span>{item.stale && <em>已过期</em>}</li>)}</ul>
            </details>}
            <p className="geo-completeness-note">只检查已关联问句与已关联事实；命中信号不等于答对，仍需人工复核。</p>
          </div>}
          <div className="geo-score-dims">
            {geoScore.dimensions.map((dim) => <div className={`geo-score-dim${dim.low ? " is-low" : ""}`} key={dim.key}>
              <div className="geo-score-dim-head"><span>{dim.label}</span><small>{dim.score}/100</small></div>
              <div className="geo-score-bar"><span className={`geo-score-fill${dim.score >= 80 ? " good" : dim.score >= 70 ? "" : " weak"}`} style={{ width: `${dim.score}%` }}/></div>
              {dim.low && <p className="geo-score-hint">{dim.hint}</p>}
              {(dim.issues ?? []).length > 0
                ? <ul className="geo-score-issues">{(dim.issues ?? []).slice(0, 3).map((issue, index) => <li key={`${dim.key}-${issue.check_key}-${issue.paragraph_index}-${index}`}>
                  <span className="geo-score-loc">第 {issue.paragraph_index} 段</span>
                  <span className="geo-score-issue-detail">{issue.detail}</span>
                  <small>“{issue.excerpt}”</small>
                </li>)}</ul>
                : <p className="geo-score-okline">本项未发现明显缺口</p>}
            </div>)}
          </div>
          <details className="geo-score-details">
            <summary>查看全部评分依据与算法口径</summary>
            <div className="geo-score-checks">
              {geoScore.dimensions.map((dim) => <div className="geo-score-check-group" key={dim.key}>
                <h4>{dim.label} · {dim.hint}</h4>
                <ul>{dim.checks.map((check) => <li key={check.key} className={check.ok ? "ok" : ""}><span>{check.label}</span><small>{check.detail}</small><em>{check.points}/{check.max_points}</em></li>)}</ul>
              </div>)}
            </div>
          </details>
          <p className="geo-score-disclaimer">{geoScore.disclaimer}</p>
        </div>}
        <details className="content-fold">
          <summary><span>正文预览</span><small>展开查看全文</small><Icon name="chevronDown" size={15}/></summary>
          <div className="sample-answer content-body-preview">{selected.body}</div>
        </details>
        {(selected.fact_links.length > 0 || history.length > 0) && <details className="content-fold">
          <summary><span>关联事实与审批记录</span><small>{selected.fact_links.length ? `${selected.fact_links.length} 条事实${staleFacts.length ? ` · ${staleFacts.length} 条待处理` : ""}` : "暂无关联事实"}{history.length ? ` · ${history.length} 条记录` : ""}</small><Icon name="chevronDown" size={15}/></summary>
          <div className="content-fold-body">
            {selected.fact_links.length > 0 && <div className="bundle-box">
              <h4>关联权威事实</h4>
              <div className="knowledge-list">{selected.fact_links.map((link) => <div className="knowledge-item" key={link.fact_id}><span><strong>{link.fact_key}：{link.fact_value}</strong><small>{link.fact_type} · 关联版本 v{link.linked_version_no}</small></span><Badge tone={link.stale ? "red" : "green"}>{link.stale ? "需重新确认" : factStatusLabel(link.approval_status)}</Badge></div>)}</div>
              {canWrite && revisedFacts.length > 0 && <div className="knowledge-actions"><Button variant="secondary" disabled={busy} onClick={() => void saveLinks(true)}>按当前版本重新确认</Button><span className="knowledge-footnote">未批准或已过期的事实仍不能通过</span></div>}
            </div>}
            <p className="knowledge-footnote">审批记录：{history.length ? history.map((row) => `${formatPersonName(row.reviewer_name) || "审核员"} ${reviewDecisionLabel(row.decision)}${row.comment ? `（${row.comment}）` : ""}`).join("；") : "暂无"}</p>
          </div>
        </details>}
        {!demo && <details className="content-fold">
          <summary><span>发布素材</span><small>可选：生成官网可用的标题、摘要和正文</small><Icon name="chevronDown" size={15}/></summary>
          <div className="content-fold-body">
            <div className="knowledge-actions"><Button variant="secondary" disabled={busy} onClick={() => void exportBundle()}>准备发布素材</Button><span className="knowledge-footnote">不改动内容库里的原稿</span></div>
            {bundle && <div className="bundle-box">
              <h4>发布素材 · 第 {bundle.version_no} 版</h4>
              <div className="bundle-meta"><span>网页标题：{bundle.title}</span><span>建议链接名：{bundle.slug_suggestion}</span><span>正式页面地址：{bundle.canonical_hint || "尚未登记官网页面，发布后按实际地址回填"}</span><span>页面摘要：{bundle.meta_description}</span></div>
              <ol className="bundle-checklist">{bundle.checklist.map((step) => <li key={step}>{step}</li>)}</ol>
              <div className="bundle-actions"><Button variant="secondary" onClick={() => void copyBundle("Markdown", bundle.markdown)}>复制正文</Button><Button variant="secondary" onClick={() => void copyBundle("HTML", bundle.html)}>复制网页内容</Button><Button variant="secondary" onClick={() => void copyBundle("JSON-LD", JSON.stringify(bundle.jsonld, null, 2))}>复制结构化数据</Button></div>
              <pre className="bundle-code">{bundle.markdown}</pre>
              <pre className="bundle-code">{bundle.html}</pre>
            </div>}
          </div>
        </details>}
        {!demo && canWrite && <div className="knowledge-actions">
          <Button variant="secondary" onClick={() => { const next = !linksOpen; setLinksOpen(next); setCitationLoading(next); setCitationError(""); }}>{linksOpen ? "收起关联" : "调整关联内容"}</Button>
          <span className="knowledge-footnote">已关联题目 {selected.question_ids.length} 个 · 来源 {selected.citation_ids.length ? "已关联" : "未关联"} · 事实 {selected.fact_ids.length} 条；只改当前版本</span>
        </div>}
        {!demo && canWrite && linksOpen && <div className="bundle-box">
          <h4>题目关联（已启用题目）</h4>
          <div className="knowledge-list">{questions.map((question) => <label className="knowledge-item" key={question.id}><span><strong>{question.code} · {question.title}</strong><small>{question.question_type}</small></span><input type="checkbox" checked={linkQuestionIds.includes(question.id)} onChange={(e) => setLinkQuestionIds((current) => e.target.checked ? [...current, question.id] : current.filter((id) => id !== question.id))}/></label>)}{!questions.length && <p className="knowledge-empty">暂无已启用题目</p>}</div>
          <h4>权威事实关联</h4>
          <p className="knowledge-footnote">正文涉及的课程周期、费用、师资、就业等事实需要挂到已批准记录；未批准、已过期或已修订都会影响审批。</p>
          <div className="knowledge-list">{facts.map((fact) => <label className="knowledge-item" key={fact.id}><span><strong>{fact.fact_key}：{fact.fact_value}</strong><small>{fact.fact_type} · v{fact.version_no} · {fact.owner || "未指定负责人"}</small></span><span><Badge tone={fact.approval_status === "approved" ? "green" : fact.approval_status === "expired" ? "red" : "amber"}>{factStatusLabel(fact.approval_status)}</Badge><input type="checkbox" checked={linkFactIds.includes(fact.id)} onChange={(e) => setLinkFactIds((current) => e.target.checked ? [...current, fact.id] : current.filter((id) => id !== fact.id))}/></span></label>)}{!facts.length && <p className="knowledge-empty">事实库暂无记录，可先去“事实库与核验”录入</p>}</div>
          <div className="source-picker">
            <div>
              <span className="field-label">关联 AI 回答（可选）</span>
              <p className="field-hint">这篇稿子针对哪条 AI 回答写的？不针对具体回答就选“不关联”。</p>
            </div>
            <input className="text-input" value={citationQuery} placeholder="搜索问题、平台或回答内容" onChange={(e) => setCitationQuery(e.target.value)}/>
            <select className="text-input" disabled={citationLoading} value={selectedCitationOption?.trace_id ?? ""} onChange={(e) => { const option = citationOptions.find((row) => row.trace_id === e.target.value); setLinkCitationIds(option?.citation_ids ?? []); }}>
              <option value="">不关联（不影响发布）</option>
              {filteredCitationOptions.map((option) => <option key={option.trace_id} value={option.trace_id}>{option.question_title} · {option.engine_name}{option.entry_name ? ` · ${option.entry_name}` : ""} · {option.citation_count} 条引用</option>)}
            </select>
            {citationLoading && <p className="knowledge-empty">正在加载来源…</p>}
            {citationError && <p className="form-error" role="alert">{citationError}</p>}
            {!citationLoading && !filteredCitationOptions.length && <p className="knowledge-empty">没有匹配的来源；可以清空搜索，或直接选“不关联”。</p>}
            {selectedCitationOption && <div className="source-preview">
              <strong>{selectedCitationOption.question_title}</strong>
              <span>{[selectedCitationOption.engine_name, selectedCitationOption.entry_name].filter(Boolean).join(" · ")} · {selectedCitationOption.citation_count} 条引用{selectedCitationOption.sampled_at ? ` · ${formatDateTime(selectedCitationOption.sampled_at)}` : ""}</span>
              {selectedCitationOption.answer_excerpt && <p>“{selectedCitationOption.answer_excerpt}”</p>}
              {!!selectedCitationOption.domains.length && <small>来源域名：{selectedCitationOption.domains.join("、")}</small>}
            </div>}
            <p className="field-hint">当前{linkCitationIds.length ? "已关联" : "未关联"}；同一条回答只保留一组来源。</p>
          </div>
          <div className="knowledge-actions"><Button disabled={busy} onClick={() => void saveLinks()}>保存关联</Button></div>
        </div>}
      </DetailModal>}
    </>}
    {activeTab === "create" && canWrite && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>新建内容草稿</h3><p>提交后正文锁定；修改需追加版本</p></div></div><form onSubmit={createContent}>
      <label className="field"><span className="field-label">标题</span><input className="text-input" required value={title} onChange={(e) => setTitle(e.target.value)}/></label>
      <label className="field"><span className="field-label">类型</span><select className="text-input" value={kind} onChange={(e) => setKind(e.target.value)}><option value="channel">渠道稿</option><option value="master">母稿</option></select></label>
      {kind === "master" && <label className="field"><span className="field-label">内容形式（可选）</span><select className="text-input" value={contentFormat} onChange={(e) => setContentFormat(e.target.value)}><option value="">暂不标注</option><option value="definition">定义</option><option value="tutorial">教程</option><option value="comparison">对比</option><option value="listicle">清单</option><option value="faq">FAQ</option><option value="case_study">案例</option></select><small className="field-hint">形式只用于内容管理与覆盖率统计，不参与 GEO 评分。</small></label>}
      {kind === "channel" && <label className="field"><span className="field-label">渠道</span><select className="text-input" required value={channelId} onChange={(e) => setChannelId(e.target.value)}><option value="">选择渠道</option>{channels.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
      {kind === "channel" && <label className="field"><span className="field-label">母稿 ID（可选）</span><input className="text-input" value={parentId} onChange={(e) => setParentId(e.target.value)}/></label>}
      <label className="field"><span className="field-label">正文</span><textarea className="text-input knowledge-textarea" required value={body} onChange={(e) => setBody(e.target.value)}/></label>
      <label className="field"><span className="field-label">变更说明</span><input className="text-input" value={changeNote} onChange={(e) => setChangeNote(e.target.value)}/></label>
      <Button type="submit" disabled={busy}>{createdItemId ? "重试保存版本" : "保存草稿"}</Button>
    </form></Panel>}
  </div>;
}
