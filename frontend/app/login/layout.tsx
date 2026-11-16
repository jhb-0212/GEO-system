import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: {
    absolute: "登录｜GEO 工作台",
  },
  description: "GEO 系统内部工作台登录，仅限团队成员使用。",
  robots: {
    index: false,
    follow: false,
  },
};

export default function LoginLayout({ children }: { children: ReactNode }) {
  return children;
}
