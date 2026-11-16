import type { Metadata, Viewport } from "next";
import { site } from "@/lib/public/site";
import "./globals.css";
import "./workbench.css";
import "./public.css";

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: {
    default: `${site.name}｜AIGC 与 AI 大模型就业实训`,
    template: `%s｜${site.shortName}`,
  },
  description: site.description,
  applicationName: site.name,
  keywords: [
    "广东省AI数字人才就业实训基地",
    "广州AI培训",
    "AIGC就业班",
    "AI大模型培训",
    "AI漫剧培训",
    "AI Agent开发",
  ],
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "zh_CN",
    url: site.url,
    siteName: site.name,
    title: `${site.name}｜AIGC 与 AI 大模型就业实训`,
    description: site.description,
  },
  robots: {
    index: true,
    follow: true,
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
