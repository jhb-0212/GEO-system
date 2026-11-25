"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import type { LeadAutoreplyRecord } from "@/lib/workbench/types";
import { DateField } from "./date-field";
import { workbenchClient } from "@/lib/workbench/client";
import type { LeadFunnel, LeadFunnelGroup, LeadVisitorReport } from "@/lib/workbench/types";

const rate = (value: number | null) => value === null ? "--" : `${(value * 100).toFixed(1)}%`;

function GroupTable({ title, caption, rows }: { title: string; caption: string; rows: LeadFunnelGroup[] }) {
  return <div className="table-scroll"><table><thead><tr><th>{title}</th><th>总数</th><th>有效</th><th>已联系</th><th>已报名</th></tr></thead><tbody>
    {rows.map((item) => <tr key={item.key}><td><strong>{item.label}</strong></td><td>{item.total}</td><td>{item.valid}</td><td>{item.contacted}</td><td>{item.enrolled}</td></tr>)}
  </tbody></table>{!rows.length && <p className="knowledge-empty">{caption}</p>}</div>;
}

export function LeadFunnelWorkspace({ mode, projectId, leadAccess, onNotice }: {
  mode: "mock" | "live";
  projectId: string;
  leadAccess: "allowed" | "forbidden" | "unavailable";
  onNotice?: (message: string) => void;
}) {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [funnel, setFunnel] = useState<LeadFunnel | null>(null);
  const [visitors, setVisitors] = useState<LeadVisitorReport | null>(null);
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  // 留言固定话术：默认关闭；打开后每条例索只自动回一次，回显必须是人工可预览的定稿
  const [autoreply, setAutoreply] = useState<LeadAutoreplyRecord | null>(null);
  const [replyDraft, setReplyDraft] = useState("");
  const [replyContact, setReplyContact] = useState(true);
  const [savingReply, setSavingReply] = useState(false);
  const requestKey = `${projectId}:${startDate}:${endDate}:${reload}`;
  const loading = mode === "live" && leadAccess === "allowed" && !!projectId && projectId !== "all" && loadedKey !== requestKey;

  useEffect(() => {
    if (mode !== "live" || leadAccess !== "allowed" || !projectId || projectId === "all") return;
    let active = true;
    // 全量口径（不受日期筛选影响）：访客去重看的是历史积累，跟着日期变会误读
    Promise.all([
      workbenchClient.leadFunnel(projectId, startDate || undefined, endDate || undefined),
      workbenchClient.leadVisitorReport(projectId).catch(() => null),
    ])
      .then(([data, visitorData]) => { if (active) { setFunnel(data); setVisitors(visitorData); setError(""); setLoadedKey(requestKey); } })
      .catch((cause) => { if (active) { setFunnel(null); setVisitors(null); setError(cause instanceof Error ? cause.message : "线索漏斗加载失败"); setLoadedKey(requestKey); } });
    return () => { active = false; };
  }, [mode, projectId, leadAccess, startDate, endDate, requestKey]);

  useEffect(() => {
    if (mode !== "live" || leadAccess !== "allowed" || !projectId || projectId === "all") { setAutoreply(null); return; }
    let cancelled = false;
    workbenchClient.leadAutoreply(projectId)
      .then((record) => {
        if (cancelled) return;
        setAutoreply(record);
        setReplyDraft(record.script);
        setReplyContact(record.include_contact);
      })
      .catch(() => { if (!cancelled) setAutoreply(null); });
    return () => { cancelled = true; };
  }, [mode, projectId, leadAccess, reload]);

  async function saveAutoreply(enabled: boolean, script = replyDraft) {
    if (!projectId || projectId === "all") return;
    setSavingReply(true);
    try {
      const saved = await workbenchClient.saveLeadAutoreply(projectId, {
        enabled,
        script,
        include_contact: replyContact,
      });
      setAutoreply(saved);
      setReplyDraft(saved.script);
      onNotice?.(enabled ? "自动回复已开启" : "自动回复已关闭");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "自动回复配置保存失败");
    } finally {
      setSavingReply(false);
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">线索漏斗请切换到真实接口模式查看。</p></Panel>;
  if (leadAccess !== "allowed") return <Panel className="lead-permission-panel"><Icon name="lock" size={25}/><h3>{leadAccess === "forbidden" ? "当前账号无权查看线索" : "请先选择项目"}</h3><p>{leadAccess === "forbidden" ? "后端拒绝了这个项目的线索请求。项目、监测等其他页面仍可使用；如需线索权限，请联系项目管理员。" : "选择项目后再查看该项目的线索漏斗。"}</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择一个项目。</p></Panel>;

  return <div className="statistics-workspace">
    <Panel className="knowledge-list-panel">
      {autoreply && (
        <>
          <div className="panel-heading">
            <div>
              <h3>留言固定话术自动回复</h3>
              <p>只发一句预先写好的模板句，不调用模型、不做意图识别、不含数字与承诺；每条线索只回一次</p>
            </div>
            <Badge tone={autoreply.enabled ? "green" : "slate"}>{autoreply.enabled ? "已开启" : "已关闭"}</Badge>
          </div>
          <textarea
            className="form-input"
            rows={4}
            value={replyDraft}
            onChange={(event) => setReplyDraft(event.target.value)}
            placeholder="例：已收到您的留言，我们会在工作时间由人工回复您。"
          />
          <label className="form-check">
            <input type="checkbox" checked={replyContact} onChange={(event) => setReplyContact(event.target.checked)} />
            附带官方公开联系方式（只取对外公开的联系人，不露内部对接号）
          </label>
          {autoreply.preview && (
            <p className="report-scope-note">访客实际会看到：{autoreply.preview}</p>
          )}
          <div className="toolbar-extra">
            <Button
              variant="secondary"
              disabled={savingReply}
              onClick={() => void saveAutoreply(!autoreply.enabled)}
            >
              {autoreply.enabled ? "关闭自动回复" : "开启自动回复"}
            </Button>
            <Button
              variant="primary"
              disabled={savingReply}
              onClick={() => void saveAutoreply(autoreply.enabled, replyDraft)}
            >
              {savingReply ? "保存中…" : "保存话术"}
            </Button>
          </div>
        </>
      )}
      <div className="panel-heading">
        <div><h3>线索漏斗</h3><p>按创建时间筛选；日期按项目时区解析。已报名计入已联系，分母为咨询总量</p></div>
        <div className="toolbar-extra">
          <DateField id="funnel-start" label="开始日期" mode="date" value={startDate} onChange={setStartDate} />
          <DateField id="funnel-end" label="结束日期" mode="date" value={endDate} onChange={setEndDate} />
          {(startDate || endDate) && <Button variant="secondary" onClick={() => { setStartDate(""); setEndDate(""); }}>清空</Button>}
          <Button variant="secondary" icon="refresh" onClick={() => setReload((value) => value + 1)}>刷新</Button>
          {funnel && <Badge tone="blue">{funnel.total} 条线索</Badge>}
        </div>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <p className="knowledge-empty">正在加载线索漏斗…</p>}
      {!loading && !funnel && !error && <p className="knowledge-empty">暂无线索数据</p>}
      {funnel && !loading && <>
        {visitors && <>
          <div className="panel-heading"><div><h3>获客访客结构</h3><p>全量口径，不受上方日期筛选影响；只存 IP 哈希做去重，不存原始地址，手工录入（无访客地址）不参与去重</p></div><Badge tone="blue">{visitors.unread_messages} 条未读留言</Badge></div>
          <div className="stats-cards">
            <div><span>去重访客</span><strong>{visitors.distinct_visitors}</strong></div>
            <div><span>带访客地址线索</span><strong>{visitors.leads_with_visitor}</strong></div>
            <div><span>重复线索率</span><strong>{visitors.repeat_rate === null ? "无法计算" : `${(visitors.repeat_rate * 100).toFixed(1)}%`}</strong></div>
            <div><span>未读访客留言</span><strong>{visitors.unread_messages}</strong></div>
          </div>
          <div className="table-scroll"><table><thead><tr><th>地区</th><th>线索数</th></tr></thead><tbody>
            {visitors.by_region.map((item) => <tr key={`r-${item.label}`}><td><strong>{item.label}</strong></td><td>{item.count}</td></tr>)}
          </tbody></table>{!visitors.by_region.length && <p className="knowledge-empty">暂无地区分组</p>}</div>
        </>}
        <div className="stats-cards">
          <div><span>咨询总量</span><strong>{funnel.total}</strong></div>
          <div><span>有效线索</span><strong>{funnel.valid}</strong></div>
          <div><span>已联系</span><strong>{funnel.contacted}</strong></div>
          <div><span>已报名</span><strong>{funnel.enrolled}</strong></div>
          <div><span>已流失</span><strong>{funnel.lost}</strong></div>
          <div><span>联系率</span><strong>{rate(funnel.contact_rate)}</strong></div>
        </div>
        <p className="stats-excluded">状态：未跟进 {funnel.status_counts.unknown} · 已联系 {funnel.status_counts.contacted} · 已报名 {funnel.status_counts.enrolled} · 已流失 {funnel.status_counts.lost}</p>
        <div className="panel-heading funnel-ai-heading"><div><h3>官网访问与 AI 来源口径</h3><p>访问/爬虫按事件发生时间，监测引用按采样时间，线索按创建时间；可追踪访问指有 session/UTM/referrer 的非 bot 访问，各类事实不合成转化率</p></div></div>
        <div className="stats-cards">
          <div><span>爬虫事件（全部）</span><strong>{funnel.ai_attribution.crawler_events}</strong></div>
          <div><span>已验证爬虫</span><strong>{funnel.ai_attribution.verified_bot_events}</strong></div>
          <div><span>非 bot 访问</span><strong>{funnel.ai_attribution.human_visits}</strong></div>
          <div><span>可追踪访问</span><strong>{funnel.ai_attribution.trackable_visits}</strong></div>
          <div><span>可追踪会话</span><strong>{funnel.ai_attribution.human_sessions}</strong></div>
          <div><span>监测 AI 引用（条）</span><strong>{funnel.ai_attribution.monitored_citations}</strong></div>
          <div><span>监测引用 URL</span><strong>{funnel.ai_attribution.monitored_citation_urls}</strong></div>
          <div><span>自报 AI 来源线索</span><strong>{funnel.ai_attribution.self_reported_ai_leads}</strong></div>
          <div><span>引擎关联线索</span><strong>{funnel.ai_attribution.engine_attributed_leads}</strong></div>
          <div><span>自报来源有效线索</span><strong>{funnel.ai_attribution.self_reported_ai_valid_leads}</strong></div>
        </div>
        <div className="table-scroll"><table><thead><tr><th>阶段</th><th>数量</th><th>占总线索</th><th>阶段转化</th></tr></thead><tbody>
          {funnel.stages.map((stage) => <tr key={stage.key}><td><strong>{stage.label}</strong></td><td>{stage.count}</td><td>{rate(stage.rate)}</td><td>{rate(stage.step_rate)}</td></tr>)}
        </tbody></table></div>
        <div className="panel-heading"><div><h3>按来源</h3><p>线索自报的原始来源，保留未归因分组</p></div><Badge tone="blue">{funnel.by_source.length} 组</Badge></div>
        <GroupTable title="来源" caption="暂无来源分组" rows={funnel.by_source} />
        <div className="panel-heading"><div><h3>按渠道</h3><p>按发布结果归因；未匹配时单列为未归因渠道</p></div><Badge tone="blue">{funnel.by_channel.length} 组</Badge></div>
        <GroupTable title="渠道" caption="暂无渠道分组" rows={funnel.by_channel} />
        <div className="panel-heading"><div><h3>按题目</h3><p>线索来源题目用于内容侧归因</p></div><Badge tone="blue">{funnel.by_question.length} 组</Badge></div>
        <GroupTable title="题目" caption="暂无题目分组" rows={funnel.by_question} />
        <div className="panel-heading"><div><h3>按 AI 引擎</h3><p>只统计带监测样本归因的线索，未归因单列</p></div><Badge tone="blue">{(funnel.by_engine ?? []).length} 组</Badge></div>
        <GroupTable title="引擎" caption="暂无引擎分组" rows={funnel.by_engine ?? []} />
        <div className="panel-heading"><div><h3>按文章</h3><p>发布文章带来的线索；没有内容项时保留未归因</p></div><Badge tone="blue">{(funnel.by_article ?? []).length} 组</Badge></div>
        <GroupTable title="文章" caption="暂无文章分组" rows={funnel.by_article ?? []} />
      </>}
    </Panel>
  </div>;
}
