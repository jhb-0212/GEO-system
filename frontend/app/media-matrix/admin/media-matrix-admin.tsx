"use client";

import { useEffect, useMemo, useState } from "react";

import {
  CATEGORIES,
  TONE_COLOR,
  type MediaBrand,
  type MediaCategory,
  type MediaMatrixCatalog,
  type MediaSection,
  type Tone,
} from "@/lib/media-matrix-data";

import styles from "./media-matrix-admin.module.css";

const TONES: Tone[] = ["red", "blue", "dark", "yellow", "green", "orange", "pink", "purple"];
const LOGO_STYLES = ["text", "square", "china", "circle", "play", "bili"] as const;

function cloneCatalog(catalog: MediaMatrixCatalog): MediaMatrixCatalog {
  return JSON.parse(JSON.stringify(catalog)) as MediaMatrixCatalog;
}

function blankItem(): MediaBrand {
  return { name: "新资源", domain: "", tone: "blue", mark: "新资源" };
}

function blankSection(): MediaSection {
  return { title: "新分组", note: "", items: [] };
}

function countItems(catalog: MediaMatrixCatalog): number {
  return catalog.reduce(
    (sum, category) => sum + category.sections.reduce((sectionSum, section) => sectionSum + section.items.filter((item) => !item.more).length, 0),
    0,
  );
}

export function MediaMatrixAdmin() {
  const [catalog, setCatalog] = useState<MediaMatrixCatalog>(cloneCatalog(CATEGORIES));
  const [activeId, setActiveId] = useState(CATEGORIES[0].id);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const activeIndex = Math.max(0, catalog.findIndex((category) => category.id === activeId));
  const active = catalog[activeIndex] ?? catalog[0];
  const total = useMemo(() => countItems(catalog), [catalog]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch("/internal/workbench/media-matrix", { cache: "no-store" });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.error?.message ?? "读取配置失败");
        }
        const payload = (await response.json()) as { data?: { payload?: MediaMatrixCatalog | null; updated_at?: string | null } };
        if (cancelled) return;
        if (Array.isArray(payload.data?.payload) && payload.data.payload.length > 0) {
          setCatalog(cloneCatalog(payload.data.payload));
          setActiveId(payload.data.payload[0].id);
        }
        setUpdatedAt(payload.data?.updated_at ?? null);
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "读取配置失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  function mutate(next: MediaMatrixCatalog) {
    setCatalog(next);
    setDirty(true);
    setNotice("");
  }

  function updateCategory(patch: Partial<MediaCategory>) {
    if (patch.id) setActiveId(patch.id);
    mutate(catalog.map((category, index) => index === activeIndex ? { ...category, ...patch } : category));
  }

  function updateSection(sectionIndex: number, patch: Partial<MediaSection>) {
    mutate(catalog.map((category, index) => {
      if (index !== activeIndex) return category;
      return {
        ...category,
        sections: category.sections.map((section, sectionPosition) => sectionPosition === sectionIndex ? { ...section, ...patch } : section),
      };
    }));
  }

  function updateItem(sectionIndex: number, itemIndex: number, patch: Partial<MediaBrand>) {
    mutate(catalog.map((category, index) => {
      if (index !== activeIndex) return category;
      return {
        ...category,
        sections: category.sections.map((section, sectionPosition) => {
          if (sectionPosition !== sectionIndex) return section;
          return {
            ...section,
            items: section.items.map((item, itemPosition) => itemPosition === itemIndex ? { ...item, ...patch } : item),
          };
        }),
      };
    }));
  }

  function removeItem(sectionIndex: number, itemIndex: number) {
    mutate(catalog.map((category, index) => {
      if (index !== activeIndex) return category;
      return {
        ...category,
        sections: category.sections.map((section, sectionPosition) => sectionPosition !== sectionIndex
          ? section
          : { ...section, items: section.items.filter((_, itemPosition) => itemPosition !== itemIndex) }),
      };
    }));
  }

  function moveItem(sectionIndex: number, itemIndex: number, direction: -1 | 1) {
    const target = itemIndex + direction;
    const section = active.sections[sectionIndex];
    if (!section || target < 0 || target >= section.items.length) return;
    const items = [...section.items];
    [items[itemIndex], items[target]] = [items[target], items[itemIndex]];
    updateSection(sectionIndex, { items });
  }

  function addItem(sectionIndex: number) {
    const section = active.sections[sectionIndex];
    if (!section) return;
    updateSection(sectionIndex, { items: [...section.items, blankItem()] });
  }

  function addSection() {
    updateCategory({ sections: [...active.sections, blankSection()] });
  }

  function addCategory() {
    const id = `group-${catalog.length + 1}`;
    const row: MediaCategory = {
      id,
      label: "新分类",
      title: "新分类",
      description: "",
      sections: [blankSection()],
    };
    mutate([...catalog, row]);
    setActiveId(id);
  }

  function removeSection(sectionIndex: number) {
    if (active.sections.length <= 1) {
      setError("每个分类至少保留一个分组");
      return;
    }
    updateCategory({ sections: active.sections.filter((_, index) => index !== sectionIndex) });
  }

  async function save() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/internal/workbench/media-matrix", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: catalog }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.error?.message ?? "保存失败");
      setDirty(false);
      setUpdatedAt(payload?.data?.updated_at ?? new Date().toISOString());
      setNotice("已保存，公开页刷新后即可看到最新目录");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!window.confirm("恢复默认目录会清除后台保存的所有修改，确定继续吗？")) return;
    setSaving(true);
    setError("");
    try {
      const response = await fetch("/internal/workbench/media-matrix", { method: "DELETE" });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.error?.message ?? "恢复失败");
      setCatalog(cloneCatalog(CATEGORIES));
      setActiveId(CATEGORIES[0].id);
      setDirty(false);
      setUpdatedAt(null);
      setNotice("已恢复默认目录");
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : "恢复失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <main className={styles.page}><p className={styles.loading}>正在读取媒体资源矩阵配置…</p></main>;
  }

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <div>
          <a href="/media-matrix" className={styles.back}>← 返回展示页</a>
          <a href="/internal/workbench" className={styles.back}>工作台</a>
        </div>
        <div className={styles.actions}>
          <span className={styles.meta}>{updatedAt ? `最近保存 ${new Date(updatedAt).toLocaleString("zh-CN")}` : "当前使用默认目录"}</span>
          <button type="button" className={styles.secondary} onClick={reset} disabled={saving}>恢复默认</button>
          <button type="button" className={styles.primary} onClick={save} disabled={saving || !dirty}>{saving ? "保存中…" : dirty ? "保存修改" : "已保存"}</button>
        </div>
      </header>

      <div className={styles.intro}>
        <div>
          <span className={styles.eyebrow}>PLATFORM MEDIA CATALOG</span>
          <h1>媒体资源矩阵后台</h1>
          <p>平台级目录，多个客户、多个项目共用。这里只维护展示用的资源类型，不代表已签约、已开通或已发布。</p>
        </div>
        <div className={styles.stat}><strong>{total}</strong><span>个资源</span></div>
      </div>

      {(error || notice) && <p className={error ? styles.error : styles.notice}>{error || notice}</p>}

      <nav className={styles.tabs} aria-label="媒体分类">
        {catalog.map((category) => (
          <button
            key={category.id}
            type="button"
            className={category.id === active.id ? styles.tabActive : styles.tab}
            onClick={() => setActiveId(category.id)}
          >
            {category.label}
            <span>{category.sections.reduce((sum, section) => sum + section.items.length, 0)}</span>
          </button>
        ))}
        <button type="button" className={styles.addTab} onClick={addCategory}>+ 分类</button>
      </nav>

      <section className={styles.categoryCard}>
        <div className={styles.categoryGrid}>
          <label>分类名称<input value={active.label} onChange={(event) => updateCategory({ label: event.target.value })} /></label>
          <label>分类 ID<input value={active.id} onChange={(event) => updateCategory({ id: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} /></label>
          <label className={styles.wide}>页面标题<input value={active.title} onChange={(event) => updateCategory({ title: event.target.value })} /></label>
          <label className={styles.full}>分类说明<textarea value={active.description} rows={2} onChange={(event) => updateCategory({ description: event.target.value })} /></label>
        </div>
      </section>

      <div className={styles.sectionList}>
        {active.sections.map((section, sectionIndex) => (
          <section className={styles.sectionCard} key={`${section.title}-${sectionIndex}`}>
            <header className={styles.sectionHead}>
              <div className={styles.sectionFields}>
                <label>分组标题<input value={section.title} onChange={(event) => updateSection(sectionIndex, { title: event.target.value })} /></label>
                <label>分组说明<input value={section.note} onChange={(event) => updateSection(sectionIndex, { note: event.target.value })} /></label>
              </div>
              <button type="button" className={styles.dangerGhost} onClick={() => removeSection(sectionIndex)}>删除分组</button>
            </header>

            <div className={styles.itemList}>
              {section.items.map((item, itemIndex) => (
                <article className={styles.itemCard} key={`${item.name}-${itemIndex}`}>
                  <div className={styles.itemHead}>
                    <span className={styles.order}>{String(itemIndex + 1).padStart(2, "0")}</span>
                    <label className={styles.checkbox}><input type="checkbox" checked={Boolean(item.more)} onChange={(event) => updateItem(sectionIndex, itemIndex, { more: event.target.checked })} />更多媒体占位</label>
                    <div className={styles.itemActions}>
                      <button type="button" onClick={() => moveItem(sectionIndex, itemIndex, -1)} disabled={itemIndex === 0}>上移</button>
                      <button type="button" onClick={() => moveItem(sectionIndex, itemIndex, 1)} disabled={itemIndex === section.items.length - 1}>下移</button>
                      <button type="button" className={styles.dangerGhost} onClick={() => removeItem(sectionIndex, itemIndex)}>删除</button>
                    </div>
                  </div>
                  {!item.more && (
                    <div className={styles.itemGrid}>
                      <label>资源名称<input value={item.name} onChange={(event) => updateItem(sectionIndex, itemIndex, { name: event.target.value })} /></label>
                      <label>域名<input value={item.domain} onChange={(event) => updateItem(sectionIndex, itemIndex, { domain: event.target.value })} placeholder="example.com" /></label>
                      <label>字标文字<input value={item.mark ?? ""} onChange={(event) => updateItem(sectionIndex, itemIndex, { mark: event.target.value })} placeholder="未上传 logo 时显示" /></label>
                      <label>字标副标题<input value={item.sub ?? ""} onChange={(event) => updateItem(sectionIndex, itemIndex, { sub: event.target.value })} placeholder="可选" /></label>
                      <label>品牌色<select value={item.tone} onChange={(event) => updateItem(sectionIndex, itemIndex, { tone: event.target.value as Tone })}>{TONES.map((tone) => <option key={tone} value={tone}>{tone}</option>)}</select><span className={styles.swatch} style={{ background: TONE_COLOR[item.tone] }} /></label>
                      <label>字标样式<select value={item.logoStyle ?? "text"} onChange={(event) => updateItem(sectionIndex, itemIndex, { logoStyle: event.target.value as MediaBrand["logoStyle"] })}>{LOGO_STYLES.map((style) => <option key={style} value={style}>{style}</option>)}</select></label>
                      <label className={styles.full}>Logo 地址<input value={item.logo ?? ""} onChange={(event) => updateItem(sectionIndex, itemIndex, { logo: event.target.value })} placeholder="/media-logos/xxx.png 或 https://…" /></label>
                    </div>
                  )}
                  {item.logo && !item.more && <img className={styles.logoPreview} src={item.logo} alt={`${item.name} logo 预览`} />}
                </article>
              ))}
            </div>
            <button type="button" className={styles.addItem} onClick={() => addItem(sectionIndex)}>+ 添加资源</button>
          </section>
        ))}
      </div>

      <div className={styles.bottomActions}>
        <button type="button" className={styles.secondary} onClick={addSection}>+ 添加分组</button>
        <button type="button" className={styles.primary} onClick={save} disabled={saving || !dirty}>{saving ? "保存中…" : "保存修改"}</button>
      </div>

      <p className={styles.footer}>说明：此页维护的是平台级展示目录；渠道签约、报价审批与发布回执仍在项目渠道台账中管理，二者不混用。</p>
    </main>
  );
}
