import type { Metadata, Viewport } from "next";

import "./globals.css";
import "./tokens.css";
import "./primitives.css";
import "./workbench.css";
import "./kit.css";
import "./kb.css";
import "./client.css";
// 表单控件尺寸修复放最后：同名选择器盖住前面各页的旧高度
import "./textareas.css";

export const metadata: Metadata = {
  title: {
    default: "GEO 工作台",
    template: "%s｜GEO 工作台",
  },
  description: "GEO 系统内部品牌运营工作台，仅限团队成员使用。",
  applicationName: "GEO 工作台",
  robots: {
    index: false,
    follow: false,
  },
  icons: {
    icon: "/favicon.svg",
  },
};

export const viewport: Viewport = {
  themeColor: "#0a2344",
  colorScheme: "light",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
