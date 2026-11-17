import { NextResponse } from "next/server";

import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode, sessionCookieName } from "@/lib/workbench/server-session";

const MAX_AGE = 60 * 60 * 8;

/**
 * 修改密码：读当前会话 token → 转后端 `/auth/password` → 用返回的新 token 覆盖 cookie。
 *
 * 后端改密会把 `token_version += 1`，旧 token 随即失效；所以这里必须把响应里的新 token
 * 写回会话，否则用户改完密码自己就被登出了。
 */
export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  }
  if (isMockMode()) {
    return NextResponse.json({ error: { code: "mock_only", message: "演示模式不支持修改密码" } }, { status: 400 });
  }

  const body = await request.json().catch(() => null);
  const current = typeof body?.current_password === "string" ? body.current_password : "";
  const next = typeof body?.new_password === "string" ? body.new_password : "";
  if (!current || !next) {
    return NextResponse.json({ error: { code: "validation_error", message: "请输入原密码和新密码" } }, { status: 400 });
  }
  if (next.length < 8 || next.length > 128) {
    return NextResponse.json({ error: { code: "validation_error", message: "新密码长度需在 8–128 位之间" } }, { status: 400 });
  }
  if (current === next) {
    return NextResponse.json({ error: { code: "password_unchanged", message: "新密码不能与原密码相同" } }, { status: 400 });
  }

  try {
    const payload = await backendRequest<{ access_token: string }>("/api/v1/auth/password", token, {
      method: "POST",
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
    const fresh = payload.data?.access_token;
    if (typeof fresh !== "string" || !fresh) {
      return NextResponse.json({ error: { code: "invalid_response", message: "改密响应缺少新令牌" } }, { status: 502 });
    }
    const response = NextResponse.json({ data: { ok: true } });
    response.cookies.set(sessionCookieName, fresh, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: MAX_AGE,
    });
    return response;
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    return NextResponse.json({ error: { code: "backend_unavailable", message: "暂时无法连接后端" } }, { status: 503 });
  }
}
