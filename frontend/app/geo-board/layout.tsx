import { connection } from "next/server";
import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { BackendError } from "@/lib/workbench/backend";
import { getSessionToken, isSessionValid } from "@/lib/workbench/server-session";

// 登录态与令牌过期都依赖请求时刻，和 /workbench 一样排除预渲染。
export const instant = false;

export default async function GeoBoardLayout({ children }: { children: ReactNode }) {
  await connection();
  const token = await getSessionToken();
  if (!token) redirect("/login?next=/geo-board");

  let valid = false;
  try {
    valid = await isSessionValid(token);
  } catch (error) {
    if (error instanceof BackendError && error.status === 403) {
      return (
        <main className="access-denied">
          <h1>无权访问数据大屏</h1>
          <p>{error.code === "project_forbidden" ? "当前账号没有这个项目的访问权限。" : "当前账号的角色没有权限查看数据大屏。"}</p>
          <a href="/login?next=/geo-board">重新登录</a>
        </main>
      );
    }
    redirect("/login?next=/geo-board");
  }
  if (!valid) redirect("/login?next=/geo-board");
  return children;
}
