import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const cookieName = "geo_workbench_session";

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const username = typeof body.username === "string" ? body.username.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!username || !password) {
    return NextResponse.json({ error: { code: "validation_error", message: "请输入账号和密码" } }, { status: 400 });
  }

  let token: string;
  if (process.env.GEO_API_MODE === "mock") {
    if (username !== "demo" || password !== "demo") {
      return NextResponse.json({ error: { code: "unauthorized", message: "演示账号或密码不正确" } }, { status: 401 });
    }
    token = "demo";
  } else {
    // Real login is deliberately fail-closed until the backend ships auth/login.
    const base = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://host.docker.internal:8000");
    try {
      const response = await fetch(new URL("/api/v1/auth/login", base), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ username, password }),
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok) {
        return NextResponse.json(payload, { status: response.status });
      }
      token = payload.data?.access_token;
      if (typeof token !== "string" || !token) {
        return NextResponse.json({ error: { code: "contract_pending", message: "登录响应格式尚未与后端确认" } }, { status: 502 });
      }
    } catch {
      return NextResponse.json({ error: { code: "backend_unavailable", message: "暂时无法连接后端登录服务" } }, { status: 503 });
    }
  }

  const response = NextResponse.json({ data: { mode: process.env.GEO_API_MODE === "mock" ? "mock" : "live" } });
  response.cookies.set(cookieName, token, {
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
  response.cookies.set(cookieName, "", { path: "/", maxAge: 0 });
  return response;
}

export async function GET() {
  const session = (await cookies()).get(cookieName)?.value;
  return NextResponse.json({ data: { authenticated: Boolean(session), mode: process.env.GEO_API_MODE === "mock" ? "mock" : "live" } });
}
