"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon, type IconName } from "@/components/ui";
import styles from "./observatory.module.css";
import type { AnswerStatus, ObservatoryData, ObservatoryRange } from "./observatory-data";

type NavItem = { label: string; icon: IconName; href: string; on?: boolean; count?: number };

const navGroups: { title: string; items: NavItem[] }[] = [
  { title: "工作台", items: [
    { label: "监测总览", icon: "layers" as IconName, href: "/observatory", on: true },
    { label: "诊断报告", icon: "pulse" as IconName, href: "/workbench?section=report" },
    { label: "内容出处", icon: "grid" as IconName, href: "/workbench?section=channels" },
    { label: "内容与发布", icon: "blocks" as IconName, href: "/workbench?section=publishing" },
  ] },
  { title: "运营", items: [
    { label: "监测问题", icon: "history" as IconName, href: "/workbench?section=questions" },
    { label: "待处理", icon: "bell" as IconName, href: "/workbench?section=samples" },
    { label: "可以做什么", icon: "spark" as IconName, href: "/workbench?section=opportunities" },
  ] },
  { title: "系统", items: [{ label: "项目设置", icon: "folder" as IconName, href: "/workbench?section=company" }] },
];

function AnswerTag({ status }: { status: AnswerStatus }) {
  const tone = status === "带链接" ? styles.tagCite : status === "链接失效" ? styles.tagBroken : status === "只提到" ? styles.tagPlain : styles.tagMuted;
  return <span className={`${styles.tag} ${tone}`}>{status}</span>;
}

export function MiniRing({ value, zero = false }: { value: number; zero?: boolean }) {
  return <span className={styles.ring} aria-hidden="true">
    <svg viewBox="0 0 38 38">
      <circle className={styles.ringBg} cx="19" cy="19" r="15" />
      <g className={styles.ringTicks}><line x1="19" y1="2" x2="19" y2="5" /><line x1="36" y1="19" x2="33" y2="19" /><line x1="19" y1="36" x2="19" y2="33" /><line x1="2" y1="19" x2="5" y2="19" /></g>
      {zero ? <circle className={styles.ringZero} cx="19" cy="19" r="15" /> : <circle className={styles.ringArc} cx="19" cy="19" r="15" pathLength="100" strokeDasharray={`${Math.min(100, value)} 100`} />}
    </svg>
  </span>;
}

export function TrendChart({ range }: { range: ObservatoryRange }) {
  const mentions = range.mentions.length ? range.mentions : [0];
  const links = range.links.length ? range.links : mentions.map(() => 0);
  const max = Math.max(6, Math.ceil(Math.max(...mentions, ...links) / 2) * 2);
  const w = 760;
  const h = 200;
  const left = 40;
  const right = 720;
  const top = 20;
  const bottom = 180;
  const span = Math.max(1, mentions.length - 1);
  const x = (index: number) => left + index * ((right - left) / span);
  const y = (value: number) => bottom - (value / max) * (bottom - top);
  const points = (values: number[]) => values.map((value, index) => `${x(index)},${y(value)}`).join(" L");
  const area = `M${points(mentions)} L${right},${bottom} L${left},${bottom} Z`;
  const gridLabels = [max, Math.round(max * 0.66), Math.round(max * 0.33), 0];
  return <div className={styles.chartBox}>
    <svg className={styles.chart} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="每天提到品牌和带链接的回答数量">
      <defs><linearGradient id="obsArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#176C6B" stopOpacity=".16" /><stop offset="1" stopColor="#176C6B" stopOpacity=".02" /></linearGradient></defs>
      {[60, 90, 120, 150, 180].map((line) => <line key={line} className={styles.grid} x1="40" y1={line} x2="720" y2={line} />)}
      {gridLabels.map((label, index) => <text key={`${label}-${index}`} x="8" y={[24, 64, 124, 154][index] ?? 184}>{label}</text>)}
      <path className={styles.area} d={area} fill="url(#obsArea)" />
      <path className={styles.line} d={`M${points(mentions)}`} />
      <path className={styles.lineAlt} d={`M${points(links)}`} />
      {mentions.map((value, index) => <circle key={`m-${index}`} className={styles.dot} cx={x(index)} cy={y(value)} r="3" />)}
      {links.map((value, index) => <circle key={`l-${index}`} className={styles.dotAlt} cx={x(index)} cy={y(value)} r="2.6" />)}
    </svg>
    <div className={styles.axis}>{range.dates.map((date, index) => <span key={`${date}-${index}`}>{date}</span>)}</div>
  </div>;
}

export function ObservatoryClient({ data }: { data: ObservatoryData }) {
  const router = useRouter();
  const [range, setRange] = useState(data.ranges.find((item) => item.days === 30)?.days ?? data.ranges[0]?.days ?? 30);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [toast, setToast] = useState("");
  const [modal, setModal] = useState<"new" | "row" | null>(null);
  const [modalQuestion, setModalQuestion] = useState("");
  const [modalStatus, setModalStatus] = useState<AnswerStatus | null>(null);
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);

  const rangeMeta = data.ranges.find((item) => item.days === range) ?? data.ranges[0];
  const tableRows = data.questions;
  const filtered = useMemo(() => tableRows.filter((row) => {
    if (filter === "review" && row.flag === "ok") return false;
    if (filter === "gap" && row.status === "带链接") return false;
    if (filter === "ok" && row.mentions === 0) return false;
    const text = `${row.question} ${row.engine} ${row.scene}`.toLowerCase();
    return !query.trim() || text.includes(query.trim().toLowerCase());
  }), [filter, query, tableRows]);

  const cited = data.citedAnswers;
  const mentioned = data.mentionedAnswers;
  const broken = data.mentions.filter((row) => row.status === "链接失效").length;
  const onlyMentioned = Math.max(0, mentioned - cited - broken);
  const absent = Math.max(0, data.totalAnswers - mentioned);
  const engineTotal = data.engines.reduce((total, engine) => total + engine.count, 0);
  const engineMax = Math.max(1, ...data.engines.map((engine) => engine.count));
  const sourceMax = Math.max(1, ...data.sources.map((source) => source.share));
  const sourceTopShare = data.sources.reduce((total, source) => total + source.share, 0);
  const otherSites = Math.max(0, data.sourcesCount - data.sources.length);
  const otherShare = Math.max(0, 100 - sourceTopShare);
  const reviewCount = tableRows.filter((row) => row.flag !== "ok").length;
  const noLinkCount = tableRows.filter((row) => row.status !== "带链接").length;
  const mentionedQuestions = tableRows.filter((row) => row.mentions > 0).length;
  const firstGap = data.questions.find((row) => row.status === "没提到") ?? data.questions[0];
  const reviewedAnswer = modal === "row" && modalStatus === "带链接";
  const writeBlocked = modal === "new" ? !data.canWriteQuestion : modal === "row" ? !data.canWriteContent : false;
  const modalTitle = reviewedAnswer ? "这条已经带链接" : modal === "new" ? "新建监测题" : "处理这条回答";
  const modalLead = reviewedAnswer
    ? "这条回答已经带着能点开的链接，不用再补写；需要看链接位置，可以到「内容出处」。"
    : writeBlocked
      ? "当前账号没有写权限，只能查看；要新建题目或创建补写草稿，请换运营编辑账号。"
      : modal === "new"
        ? "问题先加入题目库；下一轮批量生成任务时，会按项目已启用的 AI 平台自动分配。"
        : "把这条缺口变成一篇补写草稿，保存到内容审核；不会跳过审核直接发布。";

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 3400);
  }

  function openModal(mode: "new" | "row", question = "", status: AnswerStatus | null = null) {
    setModalQuestion(question);
    setModalStatus(status);
    setFormError("");
    setSaving(false);
    setModal(mode);
  }

  async function submitModal() {
    if (reviewedAnswer) {
      setModal(null);
      return;
    }
    if (writeBlocked) {
      setFormError("当前账号没有写权限，请换运营编辑账号操作");
      return;
    }
    const question = modalQuestion.trim();
    if (question.length < 2) {
      setFormError("请写一个具体的问题，至少 2 个字");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      const params = new URLSearchParams({
        action: modal === "new" ? "question" : "content",
        project_id: data.projectId,
      });
      const response = await fetch(`/internal/observatory?${params}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, source: modal === "new" ? "observatory-new" : "observatory-answer-gap" }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.error?.message ?? "提交失败，请稍后再试");
      setModal(null);
      notify(payload?.data?.message ?? (modal === "new" ? "已加入监测题目库" : "已创建补写草稿"));
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : "提交失败，请稍后再试");
    } finally {
      setSaving(false);
    }
  }

  function openSection(href: string) {
    setMobileNav(false);
    const url = new URL(href, window.location.origin);
    if (!url.searchParams.has("project_id")) url.searchParams.set("project_id", data.projectId);
    router.push(`${url.pathname}${url.search}`);
  }

  function exportCsv() {
    const header = "问题,场景,AI平台,查了几次,提到你,带链接,状态";
    const body = tableRows.map((row) => [row.question, row.scene, row.engine, row.attempts, row.mentions, row.links, row.status].join(",")).join("\n");
    const blob = new Blob([`${header}\n${body}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "geo-observatory.csv";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 800);
    notify(`已导出 ${tableRows.length} 个监测问题`);
  }

  return <div className={styles.shell}>
    {mobileNav && <button type="button" className={styles.scrim} aria-label="关闭菜单" onClick={() => setMobileNav(false)} />}
    <aside className={`${styles.side} ${mobileNav ? styles.sideOpen : ""}`}>
      <div className={styles.brand}>
        <span className={styles.logo}><i /><i /><i /></span>
        <span><strong>GEO 观察台</strong><small>SEARCH VISIBILITY</small></span>
      </div>
      <button type="button" className={styles.workspace}>
        <span className={styles.wsMark}>{data.projectName.slice(0, 1)}</span>
        <span><strong>{data.projectName}</strong><small>主项目 · 客户视图</small></span>
        <Icon name="chevronDown" size={13} />
      </button>
      <nav className={styles.nav} aria-label="主导航">
        {navGroups.map((group) => <div key={group.title} className={styles.navGroup}>
          <p>{group.title}</p>
          {group.items.map((item) => <button key={item.label} type="button" className={item.on ? styles.navOn : ""} onClick={() => openSection(item.href)}>
            <Icon name={item.icon} size={17} /><span>{item.label}</span>{item.count ? <b>{item.count}</b> : null}
          </button>)}
        </div>)}
      </nav>
      <div className={styles.sideFoot}><i />{data.mode === "live" ? "数据已接通" : data.mode === "fallback" ? "接口未连上 · 演示数据" : "演示数据"} · {data.updatedAt} 更新</div>
    </aside>

    <div className={styles.main}>
      <header className={styles.topbar}>
        <button type="button" className={styles.menuButton} aria-label="打开菜单" onClick={() => setMobileNav(true)}><Icon name="menu" size={20} /></button>
        <div className={styles.crumb}>{data.projectName} <span>→</span> <strong>监测总览</strong></div>
        <div className={styles.topRight}>
          <span className={styles.sync}><i />{data.updatedAt}</span>
          <button type="button" className={styles.iconBtn} aria-label="通知" onClick={() => openSection(`/workbench?section=samples&project_id=${encodeURIComponent(data.projectId)}`)}><Icon name="bell" size={18} /></button>
          <button type="button" className={styles.exportBtn} onClick={exportCsv}><Icon name="download" size={16} />导出</button>
          <span className={styles.account}><i>{data.userName.slice(0, 1)}</i><span><strong>{data.userName}</strong><small>内容运营</small></span><Icon name="chevronDown" size={12} /></span>
        </div>
      </header>

      <main className={styles.content}>
        <div className={styles.pageHead}>
          <div><p className={styles.kicker}>MONITORING / {data.dateLabel}</p><h1>监测总览</h1><p>用户问 AI 时，回答里有没有提到你、有没有链接到你的网站，都记在这里。先看结论，再处理下面的问题。</p></div>
          <div className={styles.headTools}>
            {!data.canWriteQuestion && !data.canWriteContent && <span className={styles.permissionHint}>当前账号只能查看，写操作需运营编辑账号</span>}
            <div className={styles.seg} role="group" aria-label="时间范围">{data.ranges.map((item) => <button type="button" key={item.days} className={range === item.days ? styles.segOn : ""} onClick={() => setRange(item.days)}>{item.days} 天</button>)}</div>
            <button type="button" className={styles.primaryBtn} onClick={() => openModal("new")} disabled={!data.canWriteQuestion} title={data.canWriteQuestion ? undefined : "当前账号没有新建题目权限，请用运营编辑账号"}><Icon name="plus" size={15} />新建监测题</button>
          </div>
        </div>

        <div className={styles.dashboard}>
          <section className={styles.insight}>
            <div className={styles.insightHead}><span className={styles.insightKicker}><i />本轮结论 / 近 30 天</span><span className={styles.badge}>{data.totalAnswers} 条可用回答</span></div>
            <p className={styles.statement}>AI 在 <span>{data.totalAnswers}</span> 条回答里，<br />提到你 <em>{mentioned}</em> 次。</p>
            <div className={styles.insightFoot}>
              <div className={styles.metrics}>
                <div><MiniRing value={data.mentionRate} /><span><b>{data.mentionRate}%</b><strong>提到你的回答</strong><small>{data.totalAnswers} 条里 {mentioned} 条</small></span></div>
                <div><MiniRing value={data.citeRate} /><span><b>{data.citeRate}%</b><strong>回答带链接</strong><small>{data.totalAnswers} 条里 {cited} 条</small></span></div>
                <div><MiniRing value={data.competitorTogether} zero={data.competitorTogether === 0} /><span><b>{data.competitorTogether}</b><strong>竞品也在</strong><small>{data.totalAnswers} 条里 {data.competitorTogether} 条</small></span></div>
              </div>
              <p className={styles.caliber}>占比按 <b>{data.totalAnswers} 条可用回答</b>算；没查成功的 {data.excludedFailed} 条先不计入{data.brandAnswers > 0 ? `。另外 ${data.brandAnswers} 条直接搜品牌的问题另算` : ""}。</p>
            </div>
          </section>

          <aside className={styles.actions}>
            <div className={styles.panelHead}><div><h2>接下来 3 件事</h2><p>按影响大小排序</p></div><span className={styles.countBadge}>{data.actions.length} 件</span></div>
            <div className={styles.actionList}>{data.actions.map((item) => <button type="button" key={item.no} onClick={() => openModal("row", item.title)}>
              <span>{item.no}</span><span><strong>{item.title}</strong><small>{item.note}</small></span><Icon name="arrowUp" size={15} />
            </button>)}</div>
            <div className={styles.actionFoot}><span>上一轮检查 {data.updatedAt.split(" ").slice(-1)[0]}</span><button type="button" onClick={() => openSection(`/workbench?section=questions&project_id=${encodeURIComponent(data.projectId)}`)}>查看全部 <Icon name="arrowRight" size={14} /></button></div>
          </aside>

          <section className={styles.trend}>
            <div className={styles.panelHead}><div><h2>最近有多少条回答提到你</h2><p>{rangeMeta?.label}</p></div><div className={styles.legend}><span><i />提到你</span><span><i className={styles.alt} />带链接</span></div></div>
            {rangeMeta && <TrendChart range={rangeMeta} />}
            <div className={styles.trendFoot}><span>最多的是 <b>{rangeMeta?.peakLabel ?? "—"}</b>，来自「{rangeMeta?.peakSource ?? "还没有提到你的回答"}」</span><span className={styles.delta}>按时间段汇总，不估算</span></div>
          </section>

          <section className={styles.sources}>
            <div className={styles.panelHead}><div><h2>AI 从哪些网站找到你</h2><p>{data.sourceLabel}</p></div><button type="button" className={styles.iconBtn} aria-label="更多网站"><Icon name="more" size={18} /></button></div>
            <div className={styles.sourceList}>{data.sources.map((source, index) => <div key={source.name} className={styles.sourceRow}>
              <span>{String(index + 1).padStart(2, "0")}</span><strong>{source.name}</strong><i><b style={{ width: `${Math.max(6, (source.share / sourceMax) * 100)}%` }} /></i><em>{source.share}%</em>
            </div>)}</div>
            {otherSites > 0 && otherShare > 0 && <p className={styles.sourceNote}>其余 {otherSites} 个网站比较分散，合计 {otherShare}%。</p>}
            <div className={styles.engineChart}>
              <div className={styles.engineHead}><span>四个 AI 平台各答了多少</span><span>共 {engineTotal} 条</span></div>
              <div className={styles.engineBars}>{data.engines.map((engine) => <div key={engine.name}><i style={{ height: `${Math.max(6, (engine.count / engineMax) * 40)}px` }} /><span>{engine.name} <b>{engine.count}</b></span></div>)}</div>
            </div>
          </section>

          <section className={styles.band}>
            <div className={styles.bandHead}>
              <div><h2>被提到的 {mentioned} 条回答是哪些</h2><p>{data.totalAnswers} 条可用回答里，{mentioned} 条提到了你。</p></div>
              <div className={styles.bandLegend}><span><i className={styles.citeDot} />带链接 {cited}</span><span><i className={styles.plainDot} />只提到 {onlyMentioned}</span><span><i className={styles.brokenDot} />链接失效 {broken}</span></div>
            </div>
            <div className={styles.bandGrid}>
              <div className={styles.mentionPanel}>
                <div className={styles.flow}><div><b>{data.totalAnswers}</b><span>可用回答</span></div><em>→</em><div className={styles.hit}><b>{mentioned}</b><span>提到你</span></div><em>→</em><div className={styles.cite}><b>{cited}</b><span>带链接</span></div></div>
                <div className={styles.ratio} role="img" aria-label={`${data.totalAnswers} 条回答中 ${mentioned} 条提到品牌，${absent} 条没提到`}><i style={{ width: `${Math.max(1, data.mentionRate)}%` }} /></div>
                <div className={styles.ratioLabels}><span>提到 {mentioned} 条 · {data.mentionRate}%</span><span>没提到 {absent} 条 · {Math.round((100 - data.mentionRate) * 10) / 10}%</span></div>
                <div className={styles.answerList}>{data.mentions.map((row) => <button type="button" key={row.id} onClick={() => openModal("row", row.question, row.status)}>
                  <span>{row.id}</span><strong>{row.question}</strong><em>{row.engine}{row.when ? ` · ${row.when}` : ""}</em><AnswerTag status={row.status} />
                </button>)}{!data.mentions.length && <p className={styles.funnelNote}>这一轮还没有回答提到你。</p>}</div>
              </div>
              <div className={styles.funnelPanel}>
                <h3>链接去哪了</h3><p>{data.citationTotal} 次链接，最后只有 {data.returnedCitations} 条回答带上了你的链接</p>
                <div className={styles.funnelRows}>
                  <div><span>所有链接</span><i><b style={{ width: "100%" }} /></i><strong>{data.citationTotal}</strong></div>
                  <div><span>{data.sourcesCount} 个网站</span><i className={styles.mid}><b style={{ width: `${data.citationTotal ? Math.max(4, (data.sourcesCount / data.citationTotal) * 100) : 0}%` }} /></i><strong>{data.sourcesCount}</strong></div>
                  <div><span>回答带链接</span><i className={styles.end}><b style={{ width: `${data.citationTotal ? Math.max(1.5, (data.returnedCitations / data.citationTotal) * 100) : 0}%` }} /></i><strong>{data.returnedCitations}</strong></div>
                </div>
                <p className={styles.funnelNote}>其余 {Math.max(0, data.citationTotal - data.returnedCitations)} 次都停在别人的网站上。</p>
                <div className={styles.quality}>
                  <div><span>这批回答有多少能用</span><strong><b>{data.qualityRate}%</b> 能用</strong></div>
                  <div className={styles.qualityTrack}><i style={{ width: `${data.qualityRate}%` }} /><b style={{ width: `${100 - data.qualityRate}%` }} /></div>
                  <div className={styles.qualityFoot}><span>能用 {data.totalAnswers}</span><span>没查成 {data.excludedFailed}</span><span>待确认 {data.excludedReview}</span></div>
                </div>
              </div>
            </div>
          </section>

          <div className={styles.notice}><Icon name="info" size={18} /><span><b>{data.noticeTitle}</b>{data.noticeNote}</span><button type="button" onClick={() => openModal("row", firstGap?.question ?? "", firstGap?.status ?? null)}>去处理 <Icon name="arrowRight" size={14} /></button></div>

          <section className={styles.tablePanel}>
            <div className={styles.tableHead}><div><h2>回答明细</h2><p><b>共 {tableRows.length} 个监测问题</b> · 覆盖 {data.totalAnswers} 条回答，当前显示 {filtered.length} 个</p></div>
              <div className={styles.tools}><label><Icon name="search" size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜问题或 AI 平台" aria-label="搜索问题或 AI 平台" /></label><button type="button" onClick={exportCsv}><Icon name="download" size={15} />导出 CSV</button></div></div>
            <div className={styles.chips}><button type="button" className={filter === "all" ? styles.chipOn : ""} onClick={() => setFilter("all")}>全部 <b>{tableRows.length}</b></button><button type="button" className={filter === "review" ? styles.chipOn : ""} onClick={() => setFilter("review")}>要处理 <b>{reviewCount}</b></button><button type="button" className={filter === "gap" ? styles.chipOn : ""} onClick={() => setFilter("gap")}>没带链接 <b>{noLinkCount}</b></button><button type="button" className={filter === "ok" ? styles.chipOn : ""} onClick={() => setFilter("ok")}>已提到 <b>{mentionedQuestions}</b></button></div>
            <div className={styles.tableHint}>左右滑动表格，查看「提到你」和「带链接」</div>
            <div className={styles.tableWrap}><table><thead><tr><th>问题</th><th>AI 平台</th><th>查了几次</th><th>提到你</th><th>带链接</th><th>状态</th><th>操作</th></tr></thead><tbody>
              {filtered.map((row) => <tr key={row.id}><td><strong>{row.question}</strong><small>{row.scene}</small></td><td>{row.engine}</td><td>{row.attempts}</td><td>{row.mentions}</td><td>{row.links}</td><td><AnswerTag status={row.status} /></td><td><button type="button" onClick={() => openModal("row", row.question, row.status)}>{row.flag === "ok" ? "查看" : "处理"} <Icon name="arrowRight" size={13} /></button></td></tr>)}
              {!filtered.length && <tr><td colSpan={7} className={styles.noResult}>没有匹配的问题，清空搜索或换一个筛选。</td></tr>}
            </tbody></table></div>
            <div className={styles.tableFoot}><span>显示 {filtered.length} 个 · 共 {tableRows.length} 个问题</span><div><button type="button">‹</button><button type="button" className={styles.pageOn}>1</button><button type="button">›</button></div></div>
            <p className={styles.tableNote}><Icon name="pulse" size={14} />只算查成功的回答：出现品牌名，算“提到你”；带能点开的链接，算“带链接”。{data.excludedFailed} 条没查成，不算。</p>
          </section>
        </div>
        <footer className={styles.footer}><span>GEO 观察台</span><span>{data.projectName} · {data.dateLabel.slice(0, 4)}</span></footer>
      </main>
    </div>

    {modal && <div className={styles.modalBackdrop} onMouseDown={(event) => { if (event.target === event.currentTarget) setModal(null); }}>
      <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="obs-modal-title">
        <div className={styles.modalHead}><div><p>{modal === "new" ? "GEO / NEW" : "GEO / ACTION"}</p><h3 id="obs-modal-title">{modalTitle}</h3></div><button type="button" onClick={() => setModal(null)} aria-label="关闭"><Icon name="close" size={18} /></button></div>
        <p className={styles.modalLead}>{modalLead}</p>
        {reviewedAnswer
          ? <div className={styles.readonlyQuestion}>{modalQuestion}</div>
          : <>
            <label className={styles.field}>{modal === "new" ? "监测问题" : "要补写的问题"}<textarea value={modalQuestion} onChange={(event) => { setModalQuestion(event.target.value); setFormError(""); }} placeholder="例如：广州 AI 培训哪家靠谱？" aria-invalid={Boolean(formError)} disabled={writeBlocked} /></label>
            {modal === "new" && <p className={styles.fieldNote}>不用选平台：生成任务时按项目已启用的 AI 平台分配。</p>}
            {formError && <p className={styles.fieldError} role="alert">{formError}</p>}
          </>}
        <div className={styles.modalFoot}>
          <span>{reviewedAnswer ? "没有写入任何数据。" : modal === "new" ? "题目先入库，生成任务后才开始检查。" : "草稿进入内容审核，写完后需人工通过。"}</span>
          <div>
            {reviewedAnswer
              ? <button type="button" className={styles.primaryBtn} onClick={() => setModal(null)}>知道了</button>
              : <button type="button" onClick={() => setModal(null)} disabled={saving}>取消</button>}
            {!reviewedAnswer && <button type="button" className={styles.primaryBtn} onClick={submitModal} disabled={saving || writeBlocked} title={writeBlocked ? "当前账号没有写权限，请用运营编辑账号" : undefined}>{saving ? "正在提交…" : modal === "new" ? "加入题目库" : "创建补写草稿"}</button>}
          </div>
        </div>
      </div>
    </div>}
    {toast && <div className={styles.toast} role="status"><Icon name="check" size={16} />{toast}</div>}
  </div>;
}
