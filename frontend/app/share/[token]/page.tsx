import type { Metadata } from "next";

import { PublicReportClient } from "@/components/public-report-client";

/** 客户只读报告：不进入搜索索引，不读取后台会话，不需要登录。 */
export const metadata: Metadata = {
  title: { absolute: "客户报告" },
  description: "AI 搜索可见性只读客户报告",
  robots: { index: false, follow: false },
};

// 令牌是运行时路径参数，不参与构建期预渲染。
export const instant = false;

export default async function SharedReportPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <PublicReportClient token={token} />;
}
