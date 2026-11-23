"use client";

import { useMemo, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel, SelectInput, TextInput } from "./ui";
import { FaqLiveWorkspace, MaterialsLiveWorkspace } from "./knowledge-live";
import { demoFaqs, demoMaterials } from "@/lib/workbench/mock-knowledge";
import type { FaqEntry, MaterialEntry, Project, Tone } from "@/lib/workbench/types";

interface WorkspaceProps {
  mode: "mock" | "live";
  projectId: string;
  projects: Project[];
  canRead?: boolean;
  canWrite?: boolean;
  canReview?: boolean;
  onNotice: (message: string) => void;
}

function projectLabel(projects: Project[], id: string): string {
  return projects.find((project) => project.id === id)?.name ?? "未知项目";
}

function DemoNotice({ mode, subject }: { mode: WorkspaceProps["mode"]; subject: string }) {
  return <div className="knowledge-notice" role="note"><Icon name="info" size={18}/><div><strong>{mode === "mock" ? "演示数据 · 不会写入服务器" : `${subject}接口等待后端交付`}</strong><p>{mode === "mock" ? "这里的修改只保留在当前页面，刷新后会恢复。" : "当前不会显示演示记录，也不会假装保存成功。页面与交互可先检查。"}</p></div></div>;
}

function faqTone(status: FaqEntry["status"]): Tone {
  if (status === "已上架") return "green";
  if (status === "已下架") return "slate";
  return "amber";
}

function FaqDemoWorkspace({ mode, projectId, projects, onNotice }: WorkspaceProps) {
  const [items, setItems] = useState<FaqEntry[]>(() => mode === "mock" ? demoFaqs.map((item) => ({ ...item })) : []);
  const [draft, setDraft] = useState<FaqEntry | null>(() => {
    const first = demoFaqs.find((item) => projectId === "all" || item.projectId === projectId);
    return mode === "mock" && first ? { ...first } : null;
  });
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const visible = useMemo(() => items.filter((item) =>
    (projectId === "all" || item.projectId === projectId) &&
    (filter === "all" || item.status === filter) &&
    `${item.question} ${item.answer}`.toLowerCase().includes(query.toLowerCase()),
  ), [items, projectId, filter, query]);

  function startNew() {
    if (mode !== "mock") { onNotice("FAQ 接口尚未交付，暂不能保存真实内容"); return; }
    setDraft({ id: "", projectId: projectId === "all" ? projects[0]?.id ?? "" : projectId, question: "", answer: "", status: "草稿", updatedAt: "未保存" });
  }

  function save(status?: FaqEntry["status"]) {
    if (mode !== "mock" || !draft) { onNotice("FAQ 接口尚未交付，未保存到服务器"); return; }
    if (!draft.projectId || !draft.question.trim() || !draft.answer.trim()) { onNotice("请先选择项目并填写问题和答案"); return; }
    const record: FaqEntry = {
      ...draft,
      id: draft.id || `FAQ-DEMO-${Date.now()}`,
      question: draft.question.trim(),
      answer: draft.answer.trim(),
      status: status ?? draft.status,
      updatedAt: "刚刚 · 演示",
    };
    setItems((current) => [record, ...current.filter((item) => item.id !== record.id)]);
    setDraft(record);
    onNotice("仅更新了当前页面的演示 FAQ，未保存到服务器");
  }

  return <div className="knowledge-workspace">
    <DemoNotice mode={mode} subject="FAQ 编辑" />
    <div className="knowledge-grid">
      <Panel className="knowledge-list-panel">
        <div className="panel-heading"><div><h3>FAQ 列表</h3><p>按项目整理常见问题与答案</p></div><Badge tone={mode === "mock" ? "amber" : "slate"}>{mode === "mock" ? "模拟记录" : "待接接口"}</Badge></div>
        <div className="knowledge-toolbar"><div className="search-field"><Icon name="search" size={16}/><input aria-label="搜索 FAQ" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索问题或答案" /></div><select className="knowledge-filter" aria-label="筛选 FAQ 状态" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">全部状态</option><option>草稿</option><option>已上架</option><option>已下架</option></select></div>
        <div className="knowledge-list">{visible.map((item) => <button key={item.id} className={`knowledge-item ${draft?.id === item.id ? "selected" : ""}`} onClick={() => setDraft({ ...item })}><span><strong>{item.question}</strong><small>{projectLabel(projects, item.projectId)} · {item.updatedAt}</small></span><Badge tone={faqTone(item.status)}>{item.status}</Badge></button>)}{!visible.length && <p className="knowledge-empty">{mode === "live" ? "等待后端 FAQ 接口，暂无真实记录" : "没有匹配的演示 FAQ"}</p>}</div>
        <div className="knowledge-panel-foot"><span>{visible.length} 条{mode === "mock" ? "演示记录" : "真实记录"}</span><Button variant="secondary" icon="plus" onClick={startNew}>新增 FAQ</Button></div>
      </Panel>
      <Panel className="knowledge-editor-panel">
        <div className="panel-heading"><div><h3>{draft?.id ? "编辑 FAQ" : "新增 FAQ"}</h3><p>编辑问题、答案及展示状态</p></div><Icon name="blocks" size={20}/></div>
        {draft ? <form onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); save(); }}>
          <SelectInput label="所属项目" value={draft.projectId} onChange={(event) => setDraft({ ...draft, projectId: event.target.value })}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</SelectInput>
          <TextInput label="问题" value={draft.question} onChange={(event) => setDraft({ ...draft, question: event.target.value })} placeholder="输入客户经常提出的问题" />
          <label className="field"><span className="field-label">答案</span><textarea className="text-input knowledge-textarea" value={draft.answer} onChange={(event) => setDraft({ ...draft, answer: event.target.value })} placeholder="输入准备发布的回答" /></label>
          <div className="knowledge-status"><span>当前状态</span><Badge tone={faqTone(draft.status)} dot>{draft.status}</Badge></div>
          <div className="knowledge-actions"><Button type="submit">保存演示修改</Button><Button type="button" variant="secondary" onClick={() => save(draft.status === "已上架" ? "已下架" : "已上架")}>{draft.status === "已上架" ? "下架（演示）" : "上架（演示）"}</Button></div>
          <p className="knowledge-footnote">操作只改变当前页面，不会发布到公开站或写入后端。</p>
        </form> : <div className="knowledge-empty editor-empty"><Icon name="folder" size={28}/><strong>尚无可编辑内容</strong><p>后端 FAQ 接口交付后再接入真实列表与保存操作。</p></div>}
      </Panel>
    </div>
  </div>;
}

function MaterialsDemoWorkspace({ mode, projectId, projects, onNotice }: WorkspaceProps) {
  const [items, setItems] = useState<MaterialEntry[]>(() => mode === "mock" ? demoMaterials.map((item) => ({ ...item })) : []);
  const [draft, setDraft] = useState<MaterialEntry | null>(() => {
    const first = demoMaterials.find((item) => projectId === "all" || item.projectId === projectId);
    return mode === "mock" && first ? { ...first } : null;
  });
  const [query, setQuery] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const visible = useMemo(() => items.filter((item) =>
    (projectId === "all" || item.projectId === projectId) &&
    `${item.title} ${item.description} ${item.fileName}`.toLowerCase().includes(query.toLowerCase()),
  ), [items, projectId, query]);

  function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode !== "mock" || !draft) { onNotice("素材接口尚未交付，未保存到服务器"); return; }
    if (!draft.title.trim()) { onNotice("请填写素材名称"); return; }
    const record = { ...draft, title: draft.title.trim(), updatedAt: "刚刚 · 演示" };
    setItems((current) => current.map((item) => item.id === record.id ? record : item));
    setDraft(record);
    onNotice("仅更新了当前页面的演示素材信息，未保存到服务器");
  }

  return <div className="knowledge-workspace">
    <DemoNotice mode={mode} subject="素材管理" />
    <div className="knowledge-grid">
      <Panel className="knowledge-list-panel">
        <div className="panel-heading"><div><h3>素材库</h3><p>按项目查看品牌图片、文档与案例</p></div><Badge tone={mode === "mock" ? "amber" : "slate"}>{mode === "mock" ? "模拟记录" : "待接接口"}</Badge></div>
        <div className="knowledge-toolbar"><div className="search-field"><Icon name="search" size={16}/><input aria-label="搜索素材" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或文件" /></div></div>
        <div className="knowledge-list">{visible.map((item) => <button key={item.id} className={`knowledge-item ${draft?.id === item.id ? "selected" : ""}`} onClick={() => setDraft({ ...item })}><span className="material-icon"><Icon name={item.category === "图片" ? "eye" : "folder"} size={19}/></span><span><strong>{item.title}</strong><small>{item.fileName} · {projectLabel(projects, item.projectId)}</small></span><Badge tone="blue">{item.category}</Badge></button>)}{!visible.length && <p className="knowledge-empty">{mode === "live" ? "等待后端素材接口，暂无真实记录" : "没有匹配的演示素材"}</p>}</div>
        <div className="knowledge-panel-foot"><span>{visible.length} 条{mode === "mock" ? "演示记录" : "真实记录"}</span></div>
      </Panel>
      <div className="knowledge-side-stack">
        <Panel className="knowledge-editor-panel">
          <div className="panel-heading"><div><h3>素材信息</h3><p>整理分类与使用说明</p></div><Icon name="folder" size={20}/></div>
          {draft ? <form onSubmit={saveMetadata}><TextInput label="素材名称" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })}/><SelectInput label="分类" value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value as MaterialEntry["category"] })}><option>图片</option><option>文档</option><option>案例</option></SelectInput><label className="field"><span className="field-label">说明</span><textarea className="text-input knowledge-textarea short" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })}/></label><div className="knowledge-file-name"><Icon name="folder" size={16}/>{draft.fileName} · 演示文件名，无真实文件</div><div className="knowledge-actions"><Button type="submit">保存演示信息</Button></div><p className="knowledge-footnote">仅修改当前页面记录，刷新后恢复。</p></form> : <p className="knowledge-empty">素材接口尚未交付，暂不能编辑真实记录。</p>}
        </Panel>
        <Panel className="knowledge-upload-panel"><div className="panel-heading"><div><h3>添加素材</h3><p>上传入口已预留，等待后端接口</p></div><Icon name="upload" size={20}/></div><label className="upload-zone knowledge-upload"><input type="file" onChange={(event) => { const file = event.target.files?.[0] ?? null; setSelectedFile(file); if (file) onNotice(`已选择 ${file.name}，但尚未上传`); }}/><Icon name="upload" size={23}/><strong>{selectedFile ? selectedFile.name : "点击选择本机文件"}</strong><span>{selectedFile ? `${(selectedFile.size / 1024).toFixed(1)} KB · 未上传到服务器` : "选择文件仅供检查，不会上传"}</span></label><div className="knowledge-actions"><Button variant="secondary" onClick={() => onNotice(selectedFile ? `已选择 ${selectedFile.name}，上传接口尚未交付，文件未上传` : "请先选择文件；上传接口尚未交付")}>检查上传状态</Button></div></Panel>
      </div>
    </div>
  </div>;
}

export function FaqWorkspace(props: WorkspaceProps) {
  if (props.mode === "live") {
    return <FaqLiveWorkspace {...props} canRead={props.canRead ?? false} canWrite={props.canWrite ?? false} canReview={props.canReview ?? false} />;
  }
  return <FaqDemoWorkspace {...props} />;
}

export function MaterialsWorkspace(props: WorkspaceProps) {
  if (props.mode === "live") {
    return <MaterialsLiveWorkspace {...props} canRead={props.canRead ?? false} canWrite={props.canWrite ?? false} />;
  }
  return <MaterialsDemoWorkspace {...props} />;
}
