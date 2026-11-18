"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { BrandProfileRecord } from "@/lib/workbench/types";

/**
 * 品牌口径配置页。
 *
 * 页面刻意把三类词条分三栏并各自说明影响面，因为它们改的是不同指标：
 * - 别名 → 提及率（brand_mentioned），严格口径，跨引擎可比；
 * - 唯一标识 → 可识别率（brand_identified），宽松口径，不覆盖提及率；
 * - 自有域名 → 信源占比（引用是否归品牌自有）。
 *
 * 把地址电话填进“别名”会让提及率失真、历史不可比，所以页面右侧实时显示
 * 生效词表，并提示两个指标各自会被哪些词触发。
 */

interface Draft {
  canonical_name: string;
  aliases: string;
  identifiers: string;
  owned_domains: string;
  notes: string;
  is_active: boolean;
}

const blank = (): Draft => ({
  canonical_name: "",
  aliases: "",
  identifiers: "",
  owned_domains: "",
  notes: "",
  is_active: true,
});

/** 一行一个词条：比逗号分隔更适合中文名与地址，也不怕词条里本身带逗号。 */
function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * 自有域名归一：剥掉协议/端口/路径、统一小写、去重。
 * 之前 splitLines 原样提交，"https://a.com/x" 和 "a.com" 会被当成两个域名，
 * 信源占比按域名精确匹配，写错一个字符就整条归不到品牌自有信源。
 */
function normalizeDomains(value: string): { domains: string[]; invalid: string[] } {
  const domains: string[] = [];
  const invalid: string[] = [];
  for (const line of splitLines(value)) {
    const host = line
      .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")
      .split(/[/?#]/)[0]
      .replace(/:\d+$/, "")
      .replace(/\.$/, "")
      .toLowerCase();
    if (!/^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(host)) {
      invalid.push(line);
      continue;
    }
    if (!domains.includes(host)) domains.push(host);
  }
  return { domains, invalid };
}

function toDraft(record: BrandProfileRecord): Draft {
  return {
    canonical_name: record.canonical_name ?? "",
    aliases: (record.aliases ?? []).join("\n"),
    identifiers: (record.identifiers ?? []).join("\n"),
    owned_domains: (record.owned_domains ?? []).join("\n"),
    notes: record.notes ?? "",
    is_active: record.is_active,
  };
}

export function BrandWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; onNotice: (message: string) => void;
}) {
  const [record, setRecord] = useState<BrandProfileRecord | null>(null);
  const [draft, setDraft] = useState<Draft>(blank());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.brandProfile(projectId)
      .then((result) => {
        if (!active) return;
        setRecord(result);
        setDraft(toDraft(result));
        setError("");
      })
      .catch((cause) => {
        if (!active) return;
        setRecord(null);
        setError(cause instanceof Error ? cause.message : "品牌口径加载失败");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, canRead, projectId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite) return;
    const canonical = draft.canonical_name.trim();
    if (!canonical) { onNotice("请填写品牌正式名"); return; }

    const aliases = splitLines(draft.aliases);
    const identifiers = splitLines(draft.identifiers);
    // 前端先挡一遍重叠：同一词条既当别名又当标识，会让提及率与可识别率互相污染。
    const overlap = aliases.filter((term) =>
      identifiers.some((other) => other.toLowerCase() === term.toLowerCase())
    );
    if (overlap.length) {
      onNotice(`「${overlap[0]}」不能同时作为别名和唯一标识：别名影响提及率，标识影响可识别率`);
      return;
    }

    const { domains: ownedDomains, invalid } = normalizeDomains(draft.owned_domains);
    if (invalid.length) {
      onNotice(`「${invalid[0]}」不是合法域名，请只填域名本身，例如 brand.example.com`);
      return;
    }

    setSaving(true);
    try {
      const saved = await workbenchClient.saveBrandProfile(projectId, {
        canonical_name: canonical,
        aliases,
        identifiers,
        owned_domains: ownedDomains,
        notes: draft.notes.trim() || null,
        is_active: draft.is_active,
      });
      setRecord(saved);
      setDraft(toDraft(saved));
      onNotice("品牌口径已保存，下次采集起生效");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">品牌口径配置仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有品牌口径查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  const configured = record?.configured ?? false;

  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div>
          <h3>品牌口径</h3>
          <p>
            {configured
              ? `正式名：${record?.canonical_name} · 别名 ${record?.aliases.length ?? 0} 个 · 标识 ${record?.identifiers.length ?? 0} 个`
              : "尚未配置：当前仍按项目名判定提及，真实品牌名可能一个都匹配不上"}
          </p>
        </div>
        {configured ? <Badge tone="green">已配置</Badge> : <Badge tone="amber">未配置</Badge>}
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && !record && !error && <p className="knowledge-empty">正在加载品牌口径…</p>}

      <div className="knowledge-list">
        <div className="knowledge-item">
          <span>
            <strong>提及词表（brand_mentioned）</strong>
            <small>{configured ? "正式名 + 别名，命中任一即判“点名提及”" : "未配置，回退到项目名/项目 code"}</small>
          </span>
          <span className="knowledge-actions">
            {(record?.effective_mention_terms ?? []).length
              ? record!.effective_mention_terms.map((term) => <Badge key={term} tone="blue">{term}</Badge>)
              : <Badge tone="slate">无</Badge>}
          </span>
        </div>
        <div className="knowledge-item">
          <span>
            <strong>唯一定位标识（brand_identified）</strong>
            <small>地址、电话、公众号名；命中只记“可识别”，不计入提及率</small>
          </span>
          <span className="knowledge-actions">
            {(record?.effective_identifier_terms ?? []).length
              ? record!.effective_identifier_terms.map((term) => <Badge key={term} tone="amber">{term}</Badge>)
              : <Badge tone="slate">未配置</Badge>}
          </span>
        </div>
        <div className="knowledge-item">
          <span>
            <strong>自有域名（信源归属）</strong>
            <small>引用命中即归为品牌自有信源，用于信源占比</small>
          </span>
          <span className="knowledge-actions">
            {(record?.effective_owned_domains ?? []).length
              ? record!.effective_owned_domains.map((term) => <Badge key={term} tone="green">{term}</Badge>)
              : <Badge tone="slate">未配置</Badge>}
          </span>
        </div>
      </div>
    </Panel>

    <Panel className="knowledge-editor-panel">
      <div className="panel-heading">
        <div><h3>编辑品牌口径</h3><p>每行一个词条；保存后从下一次采集开始生效，历史样本不重算</p></div>
        <Icon name="pulse" size={18}/>
      </div>
      <form onSubmit={save}>
        <label className="field"><span className="field-label">品牌正式名</span>
          <input className="text-input" value={draft.canonical_name} required maxLength={255} disabled={saving || !canWrite}
            placeholder="广东省AI数字人才就业实训基地"
            onChange={(event) => setDraft({ ...draft, canonical_name: event.target.value })}/>
        </label>
        <label className="field"><span className="field-label">别名（影响提及率）</span>
          <textarea className="text-input knowledge-textarea short" value={draft.aliases} disabled={saving || !canWrite}
            placeholder={"广东省成才人工智能产业孵化有限公司\n成才"}
            onChange={(event) => setDraft({ ...draft, aliases: event.target.value })}/>
          <small className="knowledge-footnote">只放名称类词条。地址、电话请填到下面的“唯一标识”，否则提及率会被污染。</small>
        </label>
        <label className="field"><span className="field-label">唯一标识（影响可识别率）</span>
          <textarea className="text-input knowledge-textarea short" value={draft.identifiers} disabled={saving || !canWrite}
            placeholder={"番山创业中心1号楼2区2楼\n13022038683"}
            onChange={(event) => setDraft({ ...draft, identifiers: event.target.value })}/>
          <small className="knowledge-footnote">越精确越好。园区名、写字楼名这类共享地名会误伤，建议写到门牌或房号。</small>
        </label>
        <label className="field"><span className="field-label">自有域名（影响信源占比）</span>
          <textarea className="text-input knowledge-textarea short" value={draft.owned_domains} disabled={saving || !canWrite}
            placeholder={"brand.example.com"}
            onChange={(event) => setDraft({ ...draft, owned_domains: event.target.value })}/>
          <small className="knowledge-footnote">不确定就先留空：凭空填一个域名会让信源占比算错。</small>
        </label>
        <label className="field"><span className="field-label">备注</span>
          <textarea className="text-input knowledge-textarea short" value={draft.notes} maxLength={5000} disabled={saving || !canWrite}
            onChange={(event) => setDraft({ ...draft, notes: event.target.value })}/>
        </label>
        <label className="rounds-checkbox"><input type="checkbox" checked={draft.is_active} disabled={saving || !canWrite}
          onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}/> 启用该品牌口径</label>
        {canWrite
          ? <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存品牌口径"}</Button></div>
          : <p className="knowledge-empty">当前账号没有维护品牌口径的权限（需要 brand.manage）。</p>}
      </form>
    </Panel>
  </div>;
}
