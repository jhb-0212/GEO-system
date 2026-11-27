import type { Metadata } from "next";

import { GeoBoardPage } from "./geo-board-page";

export const metadata: Metadata = {
  title: { absolute: "GEO 数据大屏" },
  description: "GEO 数据大屏独立页：四个主数、关键词榜、收录曲线、平台占比、报表明细与线索事件。",
  robots: { index: false, follow: false },
};

export default function GeoBoardRoutePage() {
  return <GeoBoardPage />;
}
