"use client";

import { useState, type CSSProperties } from "react";

import styles from "./media-matrix.module.css";


import {
  CATEGORIES,
  TONE_COLOR,
  type LogoStyle,
  type MediaBrand,
  type MediaCategory,
  type MediaMatrixCatalog,
} from "@/lib/media-matrix-data";

function BrandLogo({ brand }: { brand: MediaBrand }) {
  const style = {
    "--brand-color": TONE_COLOR[brand.tone],
    "--brand-text": brand.tone === "yellow" ? "#211f1c" : "#ffffff",
  } as CSSProperties;

  if (brand.logo) {
    return <img className={styles.logoImage} src={brand.logo} alt={`${brand.name} 标识`} loading="lazy" />;
  }

  if (brand.logoStyle === "square") {
    return (
      <span className={`${styles.logoSquare}`} style={style}>
        <span className={styles.squareMain}>{brand.mark ?? brand.name}</span>
        {brand.sub ? <span className={styles.squareSub}>{brand.sub}</span> : null}
      </span>
    );
  }

  if (brand.logoStyle === "china") {
    return (
      <span className={styles.logoChina}>
        {brand.mark ?? brand.name}
        <b>网</b>
      </span>
    );
  }

  if (brand.logoStyle === "circle") {
    return (
      <span className={styles.logoCircle} style={style}>
        <i />
        {brand.mark ?? brand.name}
      </span>
    );
  }

  if (brand.logoStyle === "play") {
    return (
      <span className={styles.logoPlay} style={style}>
        <i />
        {brand.mark ?? brand.name}
      </span>
    );
  }

  if (brand.logoStyle === "bili") {
    return (
      <span className={styles.logoBili}>
        <span>▷</span>
        {brand.mark ?? brand.name}
      </span>
    );
  }

  return (
    <span className={styles.logoText} style={style}>
      {brand.mark ?? brand.name}
      {brand.sub ? <small className={styles.logoSub}>{brand.sub}</small> : null}
    </span>
  );
}

export function MediaMatrix({ catalog }: { catalog: MediaMatrixCatalog }) {
  const categories = catalog.length > 0 ? catalog : CATEGORIES;
  const [activeId, setActiveId] = useState(categories[0].id);
  const active = categories.find((category) => category.id === activeId) ?? categories[0];
  const total = active.sections.reduce((sum, section) => sum + section.items.filter((item) => !item.more).length, 0);

  return (
    <main className={styles.page}>
      <section className={styles.hero}>
        <a href="/internal/workbench" className={styles.back}>返回工作台</a>
        <a href="/media-matrix/admin" className={styles.adminLink}>后台管理</a>
        <div className={styles.heroInner}>
          <span className={styles.eyebrow}>MEDIA RESOURCE MATRIX</span>
          <h1>媒体资源矩阵</h1>
          <p>新闻媒体 · 商业媒体 · 自媒体 / 新媒体</p>
          <div className={styles.heroMeta}>
            <strong>{categories.reduce((sum, category) => sum + category.sections.reduce((sectionSum, section) => sectionSum + section.items.filter((item) => !item.more).length, 0), 0)}</strong>
            个资源类型 · 按渠道类型归档
          </div>
        </div>
      </section>

      <div className={styles.tabsBar}>
        <div className={styles.tabs} role="tablist" aria-label="媒体资源分类">
          {categories.map((category) => {
            const count = category.sections.reduce((sum, section) => sum + section.items.filter((item) => !item.more).length, 0);
            const selected = category.id === activeId;
            return (
              <button
                key={category.id}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`media-panel-${category.id}`}
                className={`${styles.tab} ${selected ? styles.tabActive : ""}`}
                onClick={() => setActiveId(category.id)}
              >
                {category.label}
                <span className={styles.tabCount}>{count}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className={styles.content} id={`media-panel-${active.id}`} role="tabpanel">
        <div className={styles.categoryIntro}>
          <div>
            <h2>{active.title}</h2>
            <p>{active.description}</p>
          </div>
          <span className={styles.categoryCount}>{total} 个资源</span>
        </div>

        <div className={styles.sections}>
          {active.sections.map((section) => (
            <section key={section.title}>
              <div className={styles.sectionHead}>
                <span className={styles.sectionDot} />
                <h3>{section.title}</h3>
                <span>{section.note} · {section.items.filter((item) => !item.more).length} 个</span>
              </div>
              <div className={styles.grid}>
                {section.items.map((brand) => (
                  <article
                    key={`${section.title}-${brand.name}`}
                    className={`${styles.card} ${brand.more ? styles.moreCard : ""}`}
                    title={brand.more ? "更多媒体持续补充中" : `${brand.name} · ${brand.domain}`}
                  >
                    {brand.more ? (
                      <>
                        <span className={styles.moreDots} aria-hidden="true"><i /><i /><i /></span>
                        <span className={styles.moreText}>更多媒体</span>
                      </>
                    ) : (
                      <div className={styles.logo} aria-label={brand.name}>
                        <BrandLogo brand={brand} />
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>

        <p className={styles.footerNote}>
          <strong>说明：</strong>本页是媒体类型目录，用于按资源形态查看可拓展方向，不代表已签约、已开通或已发布。
          行业目录仅收录公开可访问、未对主流搜索引擎与 AI 抓取设全站封锁的站点；可抓取不等于已被 AI 引擎收录或引用，实际收录与引用以检索结果为准。
          行业池按客户行业、区域、预算、内容形式与合规要求筛选，不默认全部投放。
          实际投放前仍需在渠道台账中完成主体核验、报价审批与发布回执登记。
        </p>
      </div>
    </main>
  );
}
