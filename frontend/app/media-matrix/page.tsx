import type { Metadata } from "next";

import { MediaMatrix } from "./media-matrix";

export const metadata: Metadata = {
  title: "媒体资源矩阵",
  description: "新闻媒体、商业媒体、自媒体与新媒体资源类型目录。",
};

export default function MediaMatrixPage() {
  return <MediaMatrix />;
}
