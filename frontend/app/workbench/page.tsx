import type { Metadata } from "next";
import { WorkbenchApp } from "@/components/workbench-app";

export const metadata: Metadata = {
  title: { absolute: "GEO 观察台 · 监测总览" },
  description: "AI 搜索里的品牌可见度工作台：先看结论，再处理回答缺口。",
  robots: { index: false, follow: false },
};

export default function WorkbenchPage() {
  return <WorkbenchApp />;
}
