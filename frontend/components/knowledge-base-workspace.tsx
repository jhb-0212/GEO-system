"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import { formatDateTime } from "@/lib/workbench/format";
import type {
  KnowledgeCandidateFactRecord,
  KnowledgeChunkRecord,
  KnowledgeDocumentRecord,
  KnowledgeSearchItem,
  MaterialRecord,
  Tone,
} from "@/lib/workbench/types";

interface Props {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canWrite: boolean;
  onNotice: (message: string) => void;
}

const DOC_SUFFIXES = [".pdf", ".docx", ".pptx", ".txt", ".md", ".csv", ".html", ".htm"];
const STATUS_LABEL: Record<KnowledgeDocumentRecord["parse_status"], string> = {
  pending: "待解析",
  parsing: "解析中",
  ready: "已解析",
  failed: "解析失败",
  unsupported: "不支持",
};

function suffixOf(name: string): string {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index).toLowerCase() : "";
}

function statusTone(status: KnowledgeDocumentRecord["parse_status"] | "not_parsed"): Tone {
  if (status === "ready") return "green";
  if (status === "unsupported" || status === "failed") return "red";
  if (status === "parsing") return "blue";
  return "amber";
}

function pageLabel(from: number | null, to: number | null): string {
  if (!from) return "页码未知";
  return from === to || !to ? `第 ${from} 页` : `第 ${from}–${to} 页`;
}

function excerpt(text: string, limit = 360): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

export function KnowledgeWorkspace({ mode, projectId, canRead, canWrite, onNotice }: Props) {
  const [materials, setMaterials] = useState<MaterialRecord[]>([]);
  const [documents, setDocuments] = useState<KnowledgeDocumentRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selectedMaterialId, setSelectedMaterialId] = useState("");
  const [chunks, setChunks] = useState<KnowledgeChunkRecord[]>([]);
  const [candidates, setCandidates] = useState<KnowledgeCandidateFactRecord[]>([]);
  const [tab, setTab] = useState<"chunks" | "candidates">("chunks");
  const [search, setSearch] = useState("");
  const [searchItems, setSearchItems] = useState<KnowledgeSearchItem[]>([]);
  const [searchMode, setSearchMode] = useState("");
  const [searched, setSearched] = useState(false);
  const [busy, setBusy] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const targetProject = projectId === "all" ? "" : projectId;

  useEffect(() => {
    if (!canRead || !targetProject) return;
    let active = true;
    Promise.all([
      workbenchClient.materials(targetProject),
      workbenchClient.knowledgeDocuments(targetProject),
    ])
      .then(([materialPage, docPage]) => {
        if (!active) return;
        setMaterials(materialPage.data.filter((item) => DOC_SUFFIXES.includes(suffixOf(item.file_name))));
        setDocuments(docPage.data);
      })
      .catch((cause) => { if (active) onNotice(cause instanceof Error ? cause.message : "知识库加载失败"); });
    return () => { active = false; };
  }, [canRead, targetProject, reloadToken, onNotice]);

  const documentByMaterial = useMemo(() => {
    const map = new Map<string, KnowledgeDocumentRecord>();
    for (const doc of documents) map.set(doc.material_id, doc);
    return map;
  }, [documents]);

  useEffect(() => {
    if (!canRead || !targetProject || !selectedId) return;
    let active = true;
    Promise.all([
      workbenchClient.knowledgeChunks(targetProject, selectedId),
      workbenchClient.knowledgeCandidates(targetProject, undefined, selectedId),
    ])
      .then(([chunkPage, candidatePage]) => {
        if (!active) return;
        setChunks(chunkPage.data);
        setCandidates(candidatePage.data);
      })
      .catch((cause) => { if (active) onNotice(cause instanceof Error ? cause.message : "文档切块加载失败"); });
    return () => { active = false; };
  }, [canRead, targetProject, selectedId, reloadToken, onNotice]);

  const selectedDocument = documents.find((doc) => doc.id === selectedId) ?? null;
  const readyCount = documents.filter((doc) => doc.parse_status === "ready").length;
  const pendingParseCount = materials.filter((material) => {
    const doc = documentByMaterial.get(material.id);
    return !doc || doc.parse_status !== "ready";
  }).length;
  const suggestedCount = candidates.filter((row) => row.status === "suggested").length;

  function selectMaterial(materialId: string) {
    setSelectedMaterialId(materialId);
    setChunks([]);
    setCandidates([]);
    const doc = documentByMaterial.get(materialId);
    setSelectedId(doc?.parse_status === "ready" ? doc.id : "");
    setTab("chunks");
  }

  async function parseMaterial(materialId: string) {
    if (!canWrite || !targetProject) return;
    setBusy(`parse:${materialId}`);
    try {
      const doc = await workbenchClient.parseKnowledgeMaterial(targetProject, materialId);
      setDocuments((current) => [doc, ...current.filter((item) => item.id !== doc.id)]);
      if (doc.parse_status === "ready") {
        setChunks([]);
        setCandidates([]);
        setSelectedId(doc.id);
        setSelectedMaterialId(materialId);
        setTab("chunks");
        onNotice(`文档已解析：${doc.chunk_count} 个切块，${doc.candidate_count} 条候选事实`);
      } else {
        onNotice(doc.error || "文档暂不支持解析");
      }
      setReloadToken((value) => value + 1);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "文档解析失败");
    } finally {
      setBusy("");
    }
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!targetProject || !search.trim()) return;
    setBusy("search");
    try {
      const result = await workbenchClient.knowledgeSearch(targetProject, search.trim(), 8);
      setSearchItems(result.items);
      setSearchMode(result.search_mode);
      setSearched(true);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "检索失败");
    } finally {
      setBusy("");
    }
  }

  async function acceptCandidate(row: KnowledgeCandidateFactRecord) {
    if (!canWrite || !targetProject) return;
    setBusy(`accept:${row.id}`);
    try {
      const result = await workbenchClient.acceptKnowledgeCandidate(targetProject, row.id, { change_note: "知识库页面人工确认" });
      setCandidates((current) => current.map((item) => item.id === row.id ? result.candidate : item));
      onNotice("已写入事实库草稿；仍需走现有事实审批后才可用于生成");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "采纳失败");
    } finally {
      setBusy("");
    }
  }

  async function rejectCandidate(row: KnowledgeCandidateFactRecord) {
    if (!canWrite || !targetProject) return;
    setBusy(`reject:${row.id}`);
    try {
      const updated = await workbenchClient.rejectKnowledgeCandidate(targetProject, row.id, "人工判断不是可入库事实");
      setCandidates((current) => current.map((item) => item.id === row.id ? updated : item));
      onNotice("已驳回该候选事实");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "驳回失败");
    } finally {
      setBusy("");
    }
  }

  if (mode === "mock") {
    return <Panel className="knowledge-list-panel"><div className="knowledge-empty"><Icon name="info" size={18}/><p>知识库需要真实数据：演示模式不调用解析、检索与候选事实接口。请切换到真实项目后再使用。</p></div></Panel>;
  }

  if (!canRead) {
    return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前角色没有内容读取权限。</p></Panel>;
  }

  return <div className="kb-workspace">
    <div className="kb-hero">
      <div>
        <span className="kb-eyebrow">P1-4 · 知识库</span>
        <h2>文档解析、原文回查与候选事实</h2>
        <p>只做两件事：把文档切成可回查的段落；把“可能是一条事实”的句子交人工确认。候选事实不会自动进入事实库，也不会把整份文档塞给生成模型。</p>
      </div>
      <div className="kb-hero-note">
        <div><strong>{documents.length}</strong><span>已建文档</span></div>
        <div><strong>{readyCount}</strong><span>可检索</span></div>
        <div><strong>{pendingParseCount}</strong><span>待解析</span></div>
        <div><strong>{suggestedCount}</strong><span>待确认</span></div>
      </div>
    </div>

    <div className="kb-search-panel">
      <form onSubmit={submitSearch}>
        <Icon name="search" size={18}/>
        <input aria-label="检索知识库" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="用客户会问的问题检索，例如：课程多久、地址在哪、有没有认证"/>
        <Button type="submit" disabled={busy === "search" || !search.trim()}>{busy === "search" ? "检索中…" : "检索原文"}</Button>
      </form>
      <p className="kb-search-hint">{searched && searchMode === "hybrid_vector" ? "本次检索：向量语义 + 词法融合；每条结果仍回到文档、页码与原文。" : "当前检索：词法 / 中文二元组；可在配置中接 Ollama bge-m3 开启向量召回。不承诺平台收录或排名。"}</p>
      {searched && <div className="kb-search-results">
        {searchItems.length === 0 && <p className="knowledge-empty">没有命中段落。换更短、更贴近原文的词再试，或先解析相关文档。</p>}
        {searchItems.map((item) => <article key={item.chunk_id} className="kb-search-card">
          <div className="kb-search-card-head">
            <strong>{item.document_title}</strong>
            <span>{pageLabel(item.page_from, item.page_to)} · 切块 {item.chunk_no}</span>
            <Badge tone="blue">匹配度 {Math.round(item.similarity * 100)}%</Badge>
          </div>
          {item.section && <p className="kb-section">章节：{item.section}</p>}
          <p>{excerpt(item.text, 520)}</p>
          <div className="kb-terms">{item.matched_terms.map((term) => <span key={term}>{term}</span>)}</div>
        </article>)}
      </div>}
    </div>

    <div className="knowledge-grid kb-grid">
      <Panel className="knowledge-list-panel">
        <div className="panel-heading">
          <div><h3>文档与解析</h3><p>素材库中的 PDF / DOCX / PPTX / 文本 / HTML</p></div>
          <Badge tone="slate">{materials.length} 份</Badge>
        </div>
        <div className="knowledge-list">
          {materials.length === 0 && <p className="knowledge-empty">素材库里还没有可解析的文档。先到「素材管理」上传 PDF、Word 或 PPT。</p>}
          {materials.map((material) => {
            const doc = documentByMaterial.get(material.id);
            const status = doc?.parse_status ?? "not_parsed";
            const selected = selectedMaterialId === material.id;
            return <div key={material.id} role="button" tabIndex={0} className={`knowledge-item ${selected ? "selected" : ""}`} onClick={() => selectMaterial(material.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") selectMaterial(material.id); }}>
              <span className="material-icon"><Icon name="folder" size={18}/></span>
              <span>
                <strong>{material.title}</strong>
                <small>{material.file_name} · {doc ? STATUS_LABEL[doc.parse_status] : "尚未解析"}{doc?.chunk_count ? ` · ${doc.chunk_count} 块` : ""}{doc?.candidate_count ? ` · ${doc.candidate_count} 条候选` : ""}</small>
              </span>
              <span className="kb-item-actions">
                <Badge tone={statusTone(status)}>{status === "not_parsed" ? "未解析" : STATUS_LABEL[status]}</Badge>
                {canWrite && (!doc || doc.parse_status !== "ready") && <Button variant="secondary" disabled={busy === `parse:${material.id}`} onClick={(event) => { event.stopPropagation(); void parseMaterial(material.id); }}>{busy === `parse:${material.id}` ? "解析中…" : "解析"}</Button>}
              </span>
            </div>;
          })}
        </div>
        {selectedDocument?.error && <div className="kb-error"><Icon name="info" size={16}/><span>{selectedDocument.error}</span></div>}
      </Panel>

      <Panel className="knowledge-editor-panel">
        <div className="panel-heading">
          <div><h3>{selectedDocument ? selectedDocument.material_title : "选择一份文档"}</h3><p>{selectedDocument ? `${selectedDocument.file_name || ""} · ${pageLabel(1, selectedDocument.page_count)}` : "解析后查看切块与候选事实"}</p></div>
          {selectedDocument && <Badge tone={statusTone(selectedDocument.parse_status)}>{STATUS_LABEL[selectedDocument.parse_status]}</Badge>}
        </div>
        {!selectedDocument && <p className="knowledge-empty">左侧选中一份已解析文档，或用「解析」按钮生成切块。</p>}
        {selectedDocument && <div className="kb-doc-meta">
          <span>页码 <strong>{selectedDocument.page_count ?? "—"}</strong></span>
          <span>字符 <strong>{selectedDocument.char_count.toLocaleString()}</strong></span>
          <span>切块 <strong>{selectedDocument.chunk_count}</strong></span>
          <span>候选 <strong>{selectedDocument.candidate_count}</strong></span>
          <span>检索 <strong>{selectedDocument.search_mode === "hybrid_vector" ? "向量+词法" : "词法"}</strong></span>
          <span>解析于 <strong>{selectedDocument.parsed_at ? formatDateTime(selectedDocument.parsed_at) : "—"}</strong></span>
        </div>}
        {selectedDocument && <div className="kb-tabs">
          <button className={tab === "chunks" ? "active" : ""} onClick={() => setTab("chunks")}>原文切块 {chunks.length}</button>
          <button className={tab === "candidates" ? "active" : ""} onClick={() => setTab("candidates")}>候选事实 {candidates.length}</button>
        </div>}
        {selectedDocument && tab === "chunks" && <div className="kb-chunk-list">
          {chunks.length === 0 && <p className="knowledge-empty">没有可显示的切块。</p>}
          {chunks.map((chunk) => <article key={chunk.id} className="kb-chunk">
            <div className="kb-chunk-head"><strong>#{chunk.chunk_no}</strong><span>{pageLabel(chunk.page_from, chunk.page_to)}</span><span>约 {chunk.token_count} token</span>{chunk.section && <span>章节：{chunk.section}</span>}</div>
            <p>{excerpt(chunk.text, 700)}</p>
          </article>)}
        </div>}
        {selectedDocument && tab === "candidates" && <div className="kb-candidate-list">
          {candidates.length === 0 && <p className="knowledge-empty">这份文档还没有抽出候选事实。可能都是操作步骤、形容词或过短句子。</p>}
          {candidates.map((row) => <article key={row.id} className={`kb-candidate ${row.status}`}>
            <div className="kb-candidate-head">
              <Badge tone={row.status === "suggested" ? "amber" : row.status === "accepted" ? "green" : "slate"}>{row.status === "suggested" ? "待确认" : row.status === "accepted" ? "已采纳" : "已驳回"}</Badge>
              <span>{pageLabel(row.source_page, row.source_page)}</span>
              <span>置信 {Math.round(row.confidence * 100)}%</span>
            </div>
            <p className="kb-claim">{row.claim_text}</p>
            <div className="kb-candidate-meta">
              <span>建议类型 <strong>{row.suggested_fact_type}</strong></span>
              <span>建议标识 <strong>{row.suggested_fact_key}</strong></span>
              {row.fact_id && <span>事实 ID <strong>{row.fact_id.slice(0, 8)}…</strong></span>}
            </div>
            {row.status === "suggested" && canWrite && <div className="kb-candidate-actions">
              <Button variant="secondary" disabled={busy === `reject:${row.id}`} onClick={() => void rejectCandidate(row)}>{busy === `reject:${row.id}` ? "处理中…" : "驳回"}</Button>
              <Button disabled={busy === `accept:${row.id}`} onClick={() => void acceptCandidate(row)}>{busy === `accept:${row.id}` ? "采纳中…" : "采纳为事实草稿"}</Button>
            </div>}
          </article>)}
        </div>}
      </Panel>
    </div>
  </div>;
}
