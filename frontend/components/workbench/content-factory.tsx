"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Panel, TextInput } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { ContentTemplateRecord, TemplateGenerationRecord } from "@/lib/workbench/types";

/**
 * B1 内容工厂：把「渠道 × 题型」的固定骨架沉淀成模板，一键生成草稿。
 *
 * 槽位由后端从骨架里解析（`{{名称}}`），页面上的槽位预览只用于即时提示，
 * 真正校验与渲染发生在生成接口里——不能出现前端放行、后端拒收的口径分裂。
 * 生成出来的是普通草稿，仍要走审核流程。
 */

const CHANNEL_OPTIONS = [
  { value: "", label: "不限渠道" },
  { value: "own_site", label: "自有官网" },
  { value: "content_platform", label: "内容平台" },
  { value: "video", label: "视频平台" },
  { value: "community", label: "社区" },
  { value: "encyclopedia", label: "百科" },
  { value: "local_media", label: "地方媒体" },
  { value: "industry_media", label: "行业媒体" },
  { value: "b2b", label: "B2B 商贸平台" },
  { value: "institution", label: "院校机构" },
];

const QUESTION_OPTIONS = [
  { value: "", label: "不限题型" },
  { value: "brand", label: "品牌题" },
  { value: "general", label: "通用题" },
];

const SLOT_PREVIEW = /\{\{\s*([\w\u4e00-\u9fff-]+)\s*\}\}/g;

function previewSlots(skeleton: string): string[] {
  const seen: string[] = [];
  for (const match of skeleton.matchAll(SLOT_PREVIEW)) {
    if (!seen.includes(match[1])) seen.push(match[1]);
  }
  return seen;
}

export function ContentFactoryWorkspace({
  mode,
  projectId,
  canRead,
  canWrite,
  onNotice,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canWrite: boolean;
  onNotice: (message: string) => void;
}) {
  const [templates, setTemplates] = useState<ContentTemplateRecord[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [channel, setChannel] = useState("");
  const [questionType, setQuestionType] = useState("");
  const [skeleton, setSkeleton] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [generated, setGenerated] = useState<TemplateGenerationRecord[]>([]);

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const loading = active && loadedFor !== projectId;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    workbenchClient.contentTemplates(projectId)
      .then((page) => {
        if (cancelled) return;
        setTemplates(page.data);
        setError("");
      })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "模板加载失败"); })
      .finally(() => { if (!cancelled) setLoadedFor(projectId); });
    return () => { cancelled = true; };
  }, [projectId, active]);

  const slots = previewSlots(skeleton);

  async function create() {
    if (!canWrite) return;
    if (!name.trim()) { onNotice("给模板起个名字"); return; }
    if (!skeleton.trim()) { onNotice("写一段骨架再保存"); return; }
    if (!slots.length) { onNotice("骨架里至少要有一个 {{槽位}} 占位"); return; }
    setSaving(true);
    try {
      const created = await workbenchClient.createContentTemplate(projectId, {
        name: name.trim(),
        channel_category: channel || null,
        question_type: questionType || null,
        skeleton,
        notes: notes.trim() || null,
      });
      setTemplates((current) => [created, ...current]);
      setName("");
      setSkeleton("");
      setNotes("");
      onNotice(`模板已保存，解析出 ${created.slots.length} 个槽位`);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "模板保存失败");
    } finally {
      setSaving(false);
    }
  }

  function collect(item: TemplateGenerationRecord) {
    setGenerated((current) => [item, ...current].slice(0, 5));
  }

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不展示内容工厂" description="模板与生成都依赖真实项目内容，演示数据不参与。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看内容工厂" description="当前账号缺少内容读取能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="模板按项目存放；在右上角选择具体项目后再用。" />;
  }
  if (loading) return <StatePlaceholder kind="loading" title="正在加载内容模板" />;
  if (error) return <StatePlaceholder kind="error" title="模板加载失败" description={error} />;

  return (
    <div className="report-layout">
      {canWrite && (
        <Panel title="新建模板">
          <div className="factory-form">
            <TextInput label="模板名称 *" value={name} maxLength={120} placeholder="例如：小红书校区种草" onChange={(event) => setName(event.target.value)} />
            <div className="factory-row">
              <label className="field">
                <span className="field-label">目标渠道</span>
                <select className="text-input" value={channel} onChange={(event) => setChannel(event.target.value)}>
                  {CHANNEL_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label className="field">
                <span className="field-label">题型</span>
                <select className="text-input" value={questionType} onChange={(event) => setQuestionType(event.target.value)}>
                  {QUESTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
            </div>
            <label className="field">
              <span className="field-label">骨架 *（用 {"{{槽位}}"} 标记要手填的位置）</span>
              <textarea
                className="text-input"
                rows={7}
                value={skeleton}
                placeholder={"【{{品牌}}】{{卖点}}\n\n校区地址：{{地址}}\n适合人群：{{人群}}\n\n{{结尾行动指引}}"}
                onChange={(event) => setSkeleton(event.target.value)}
              />
            </label>
            <p className="factory-hint">
              {slots.length === 0
                ? "还没有槽位。骨架里加 {{品牌}} 这类占位，生成时才会要求填值。"
                : `识别到 ${slots.length} 个槽位：${slots.join("、")}（生成时全部必填）`}
            </p>
            <label className="field"><span className="field-label">备注</span><textarea className="text-input" rows={2} maxLength={2000} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
            <div className="basic-actions"><Button disabled={saving} onClick={() => void create()}>{saving ? "保存中…" : "保存模板"}</Button></div>
          </div>
        </Panel>
      )}

      {templates.length === 0 ? (
        <StatePlaceholder kind="empty" compact title="还没有内容模板" description="先把一类稿子的固定骨架存下来，之后同类稿子只填槽位就能出草稿。" />
      ) : (
        <div className="factory-list">
          {templates.map((template) => (
            <TemplateCard key={template.id} template={template} projectId={projectId} canWrite={canWrite} onNotice={onNotice} onGenerated={collect} />
          ))}
        </div>
      )}

      {generated.length > 0 && (
        <Panel title="本次生成的草稿">
          <ul className="factory-generated">
            {generated.map((item) => (
              <li key={item.version_id}>
                <strong>{item.title}</strong>
                <span className="factory-hint"> · 状态 {item.status} · hash {item.content_hash.slice(0, 10)}</span>
                <pre className="factory-body">{item.body}</pre>
              </li>
            ))}
          </ul>
          <p className="factory-hint">草稿已进内容库，去「内容审核」提交审核后才会进入发布与投喂。</p>
        </Panel>
      )}
    </div>
  );
}

function TemplateCard({
  template,
  projectId,
  canWrite,
  onNotice,
  onGenerated,
}: {
  template: ContentTemplateRecord;
  projectId: string;
  canWrite: boolean;
  onNotice: (message: string) => void;
  onGenerated: (item: TemplateGenerationRecord) => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);

  async function generate() {
    if (!canWrite) return;
    if (!title.trim()) { onNotice("给这篇草稿起个标题"); return; }
    setSaving(true);
    try {
      const result = await workbenchClient.generateFromTemplate(projectId, template.id, { title: title.trim(), slot_values: values });
      onGenerated(result);
      setTitle("");
      setValues({});
      setOpen(false);
      onNotice("草稿已生成，去内容审核走流程");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "生成失败");
    } finally {
      setSaving(false);
    }
  }

  async function toggle() {
    if (!canWrite) return;
    setToggling(true);
    try {
      const updated = await workbenchClient.updateContentTemplate(projectId, template.id, { is_active: !template.is_active });
      onNotice(updated.is_active ? "模板已启用" : "模板已停用，停用后不能生成");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setToggling(false);
    }
  }

  return (
    <Panel className="factory-card">
      <div className="factory-card-head">
        <div>
          <strong>{template.name}</strong>
          <p className="factory-hint">
            {template.channel_category || "不限渠道"} · {template.question_type || "不限题型"} · {template.slots.length} 个槽位
            {template.notes ? ` · ${template.notes}` : ""}
          </p>
        </div>
        <Badge tone={template.is_active ? "green" : "slate"}>{template.is_active ? "启用" : "已停用"}</Badge>
      </div>

      <pre className="factory-skeleton">{template.skeleton}</pre>
      <div className="factory-chips">
        {template.slots.map((slot) => <span className="basic-cat-chip" key={slot.key}>{slot.label}</span>)}
      </div>

      {canWrite && (
        <div className="basic-actions">
          <Button variant="quiet" onClick={() => setOpen((current) => !current)}>{open ? "收起" : "按此模板生成"}</Button>
          <Button variant="quiet" disabled={toggling} onClick={() => void toggle()}>{template.is_active ? "停用模板" : "重新启用"}</Button>
        </div>
      )}

      {open && template.is_active && (
        <div className="factory-generate">
          <TextInput label="草稿标题 *" value={title} maxLength={255} onChange={(event) => setTitle(event.target.value)} />
          {template.slots.map((slot) => (
            <TextInput
              key={slot.key}
              label={`${slot.label}${slot.required ? " *" : ""}`}
              value={values[slot.key] ?? ""}
              onChange={(event) => setValues((current) => ({ ...current, [slot.key]: event.target.value }))}
            />
          ))}
          <div className="basic-actions"><Button disabled={saving} onClick={() => void generate()}>{saving ? "生成中…" : "生成草稿"}</Button></div>
        </div>
      )}
    </Panel>
  );
}
