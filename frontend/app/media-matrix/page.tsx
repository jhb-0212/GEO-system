import type { Metadata } from "next";

import { CATEGORIES, type MediaMatrixCatalog } from "@/lib/media-matrix-data";

import { MediaMatrix } from "./media-matrix";

export const metadata: Metadata = {
  title: "媒体资源矩阵",
  description: "新闻媒体、商业媒体、自媒体与新媒体资源类型目录。",
};

// 目录可在后台修改，不能参与构建期预渲染。
export const instant = false;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

async function loadCatalog(): Promise<MediaMatrixCatalog> {
  try {
    const response = await fetch(new URL("/api/v1/media-matrix/catalog", apiBase()), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return CATEGORIES;
    const payload = (await response.json()) as { data?: { payload?: MediaMatrixCatalog | null } };
    const catalog = payload?.data?.payload;
    return Array.isArray(catalog) && catalog.length > 0 ? catalog : CATEGORIES;
  } catch {
    // 目录页是对外展示入口，后端短暂不可用时保留默认目录，不把 502 抛给访问者。
    return CATEGORIES;
  }
}

export default async function MediaMatrixPage() {
  const catalog = await loadCatalog();
  return <MediaMatrix catalog={catalog} />;
}
