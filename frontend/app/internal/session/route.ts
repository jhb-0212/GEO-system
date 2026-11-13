import { NextResponse } from "next/server";
import { BackendError } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode, isSessionValid, sessionCookieName } from "@/lib/workbench/server-session";

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const username = typeof body.username === "string" ? body.username.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!username || !password) {
    return NextResponse.json({ error: { code: "validation_error", message: "请输入账号和密码" } }, { status: 400 });
  }

  let token: string;
  if (isMockMode()) {
    if (username !== "demo" || password !== "demo") {
      return NextResponse.json({ error: { code: "unauthorized", message: "演示账号或密码不正确" } }, { status: 401 });
    }
    token = "demo";
  } else {
    const base = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
    try {
      const response = await fetch(new URL("/api/v1/auth/login", base), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ username, password }),
        cache: "no-store",
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        return NextResponse.json(payload?.error ? payload : { error: { code: "backend_error", message: "登录失败" } }, { status: response.status });
      }
      token = payload?.data?.access_token;
      if (typeof token !== "string" || !token) {
        return NextResponse.json({ error: { code: "invalid_response", message: "登录响应缺少 access_token" } }, { status: 502 });
      }
    } catch {
      return NextResponse.json({ error: { code: "backend_unavailable", message: "暂时无法连接后端登录服务" } }, { status: 503 });
    }
  }

  const response = NextResponse.json({ data: { mode: isMockMode() ? "mock" : "live" } });
  response.cookies.set(sessionCookieName, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 8,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ data: { ok: true } });
  response.cookies.set(sessionCookieName, "", { path: "/", maxAge: 0 });
  return response;
}

export async function GET() {
  const token = await getSessionToken();
  const mode = isMockMode() ? "mock" : "live";
  if (!token) return NextResponse.json({ data: { authenticated: false, mode } });

  try {
    const authenticated = await isSessionValid(token);
    const response = NextResponse.json({ data: { authenticated, mode } });
    if (!authenticated) response.cookies.set(sessionCookieName, "", { path: "/", maxAge: 0 });
    return response;
  } catch (error) {
    if (error instanceof BackendError && error.status === 403) {
      return NextResponse.json({ error: { code: error.code, message: "当前账号没有工作台访问权限" } }, { status: 403 });
    }
    return NextResponse.json({ error: { code: "backend_unavailable", message: "暂时无法校验登录状态" } }, { status: 503 });
  }
}
