import type { MetadataRoute } from "next";

import { siteBaseUrl } from "@/lib/site-url";

/**
 * 公开微站 sitemap：只列已发布站点。
 * 数据来自后端公开索引接口；取不到就返回空清单，不抛错、不阻塞 robots。
 */

// cacheComponents 下 Route Handler 不支持 revalidate / instant 段配置；
// 列表每次现取（fetch cache: no-store），站点数不多，不设缓存也不会成为负担。

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

function baseUrl() {
  return siteBaseUrl();
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = baseUrl();
  try {
    const response = await fetch(`${apiBase()}/api/v1/public/sites`, { cache: "no-store" });
    if (!response.ok) return [];
    const payload = await response.json();
    const rows = (payload?.data ?? []) as { slug: string; updated_at: string | null }[];
    return rows.map((row) => ({
      url: `${base}/s/${encodeURIComponent(row.slug)}`,
      lastModified: row.updated_at ? new Date(row.updated_at) : undefined,
      changeFrequency: "weekly" as const,
      priority: 0.8,
    }));
  } catch {
    return [];
  }
}
