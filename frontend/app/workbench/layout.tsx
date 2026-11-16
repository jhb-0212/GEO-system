import { connection } from "next/server";
import type { Metadata } from "next";
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

function LoginGate({ title, description, href, action }: { title: string; description: string; href: string; action: string }) {
  return (
    <main className="access-denied">
      <h1>{title}</h1>
      <p>{description}</p>
      <a href={href}>{action}</a>
    </main>
  );
}

export default async function WorkbenchLayout({ children }: LayoutProps<"/workbench">) {
  // Auth validation depends on request time and token expiry; exclude it from prerendering.
  await connection();
  const token = await getSessionToken();
  if (!token) {
    return (
      <LoginGate
        title="请先登录"
        description="工作台需要登录后访问。登录成功后会回到工作台。"
        href="/login"
        action="前往登录"
      />
    );
  }

  let valid: boolean;
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
    return (
      <LoginGate
        title="认证服务暂不可用"
        description="暂时无法验证登录状态，请稍后重试。"
        href="/login?reason=unavailable"
        action="重新登录"
      />
    );
  }
  if (!valid) {
    return (
      <LoginGate
        title="登录已过期"
        description="当前登录状态已失效，请重新登录。"
        href="/login?reason=expired"
        action="重新登录"
      />
    );
  }
  return children;
}
