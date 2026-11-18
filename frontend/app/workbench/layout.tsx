import { connection } from "next/server";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { BackendError } from "@/lib/workbench/backend";
import { getSessionToken, isSessionValid } from "@/lib/workbench/server-session";

export const metadata: Metadata = {
  title: {
    absolute: "GEO 工作台",
  },
  description: "GEO 系统内部品牌运营工作台。",
  robots: {
    index: false,
    follow: false,
  },
};

// Request-bound auth deliberately opts this layout out of instant-navigation validation.
export const instant = false;

export default async function WorkbenchLayout({ children }: LayoutProps<"/workbench">) {
  // Auth validation depends on request time and token expiry; exclude it from prerendering.
  await connection();
  const token = await getSessionToken();
  if (!token) redirect("/login");

  let valid = false;
  try {
    valid = await isSessionValid(token);
  } catch (error) {
    if (error instanceof BackendError && error.status === 403) {
      return (
        <main className="access-denied">
          <h1>无权访问工作台</h1>
          <p>{error.code === "project_forbidden" ? "当前账号没有这个项目的访问权限。" : "当前账号的角色没有访问权限。"}</p>
          <a href="/login">返回登录页</a>
        </main>
      );
    }
    // 认证服务异常或登录态无法校验时，直接回到登录界面，由登录流程给出具体提示。
    redirect("/login");
  }
  if (!valid) redirect("/login");
  return children;
}
