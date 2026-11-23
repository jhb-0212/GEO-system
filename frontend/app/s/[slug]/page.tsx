import type { Metadata } from "next";
import { notFound } from "next/navigation";

/**
 * K8 公开微站：服务端直连后端读取已发布内容。
 * 未发布 / 不存在统一 notFound()，与接口的 404 口径一致，不区分「没有这个站」和「还没发布」。
 */

// 站点内容随后台改动随时变化：不参与构建期预渲染，也不走缓存组件。
export const instant = false;

type ModulePayload = {
  module_type: "home" | "services" | "news" | "download" | "poster" | "card";
  title: string;
  content: Record<string, unknown>;
};

type SitePayload = {
  slug: string;
  title: string;
  intro: string | null;
  modules: ModulePayload[];
};

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

async function loadSite(slug: string): Promise<SitePayload | null> {
  try {
    const response = await fetch(`${apiBase()}/api/v1/public/sites/${encodeURIComponent(slug)}`, { cache: "no-store" });
    if (!response.ok) return null;
    const payload = await response.json();
    return (payload?.data ?? null) as SitePayload | null;
  } catch {
    return null;
  }
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asItems(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : [];
}

function Module({ module }: { module: ModulePayload }) {
  const content = module.content ?? {};
  if (module.module_type === "home") {
    const headline = asString(content.headline);
    const paragraphs = Array.isArray(content.paragraphs) ? content.paragraphs.map(asString).filter(Boolean) : [];
    const links = asItems(content.links);
    return (
      <section className="site-module">
        <h2>{module.title}</h2>
        {headline && <p className="site-headline">{headline}</p>}
        {paragraphs.map((text, index) => <p key={index}>{text}</p>)}
        {links.length > 0 && <div className="site-links">
          {links.map((link, index) => {
            const url = asString(link.url);
            const label = asString(link.label) || url;
            return url ? <a key={index} href={url}>{label}</a> : null;
          })}
        </div>}
      </section>
    );
  }
  if (module.module_type === "services") {
    const items = asItems(content.items);
    return (
      <section className="site-module">
        <h2>{module.title}</h2>
        <div className="site-cards">
          {items.map((item, index) => (
            <div className="site-card" key={index}>
              <h3>{asString(item.name)}</h3>
              <p>{asString(item.desc)}</p>
            </div>
          ))}
        </div>
      </section>
    );
  }
  if (module.module_type === "news") {
    const items = asItems(content.items);
    return (
      <section className="site-module">
        <h2>{module.title}</h2>
        <ul className="site-list">
          {items.map((item, index) => {
            const url = asString(item.url);
            const title = asString(item.title);
            return <li key={index}>{url ? <a href={url}>{title || url}</a> : title}<span>{asString(item.date)}</span></li>;
          })}
        </ul>
      </section>
    );
  }
  if (module.module_type === "download") {
    const items = asItems(content.items);
    return (
      <section className="site-module">
        <h2>{module.title}</h2>
        <ul className="site-list">
          {items.map((item, index) => {
            const url = asString(item.url);
            const name = asString(item.name);
            return <li key={index}>{url ? <a href={url} target="_blank" rel="noreferrer noopener">{name || "下载"}</a> : name}</li>;
          })}
        </ul>
      </section>
    );
  }
  if (module.module_type === "poster") {
    const items = asItems(content.items);
    return (
      <section className="site-module">
        <h2>{module.title}</h2>
        <div className="site-posters">
          {items.map((item, index) => {
            const image = asString(item.image_url);
            return image ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <figure key={index}><img src={image} alt={asString(item.title)} /></figure>
            ) : null;
          })}
        </div>
      </section>
    );
  }
  // card：联系方式落地，不做二维码解析
  const qrcode = asString(content.qrcode_url);
  return (
    <section className="site-module site-card-block">
      <h2>{module.title}</h2>
      <div>
        <strong>{asString(content.name)}</strong>
        <span>{asString(content.role)}</span>
        <p>{asString(content.phone)} {asString(content.wechat)}</p>
      </div>
      {qrcode && <figure>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={qrcode} alt="联系二维码" />
      </figure>}
    </section>
  );
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const site = await loadSite(slug);
  return { title: site?.title ?? "站点", description: site?.intro ?? undefined };
}

export default async function PublicSitePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const site = await loadSite(slug);
  if (!site) notFound();
  return (
    <main className="site-shell">
      <header className="site-header">
        <h1>{site.title}</h1>
        {site.intro && <p>{site.intro}</p>}
      </header>
      <div className="site-body">
        {site.modules.map((module) => <Module key={module.module_type} module={module} />)}
      </div>
      <footer className="site-footer">本站仅展示已发布内容</footer>
    </main>
  );
}
