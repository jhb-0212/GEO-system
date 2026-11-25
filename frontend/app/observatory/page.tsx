import type { Metadata } from "next";
import { connection } from "next/server";
import { redirect } from "next/navigation";

export const metadata: Metadata = {
  title: { absolute: "GEO 观察台 · 监测总览" },
  description: "AI 搜索里的品牌可见度工作台：先看结论，再处理回答缺口。",
  robots: { index: false, follow: false },
};

export const instant = false;

/** 观察台已经成为旧工作台里的「监测总览」，独立路由只做兼容跳转，避免出现第二套导航。 */
export default async function ObservatoryPage({ searchParams }: { searchParams: Promise<{ project_id?: string }> }) {
  await connection();
  const params = await searchParams;
  const query = params.project_id ? `?project_id=${encodeURIComponent(params.project_id)}` : "";
  redirect(`/workbench${query}`);
}
