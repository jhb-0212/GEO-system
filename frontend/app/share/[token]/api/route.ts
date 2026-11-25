import { NextResponse } from "next/server";

/**
 * 客户报告 BFF：把浏览器请求转发到后端公开接口。
 * 不读取、不要求工作台会话；访问控制由后端令牌、密码和限流共同完成。
 */

const TOKEN = /^[A-Za-z0-9_-]{20,128}$/;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

function failure() {
  return NextResponse.json({ error: { code: "report_unavailable", message: "报告服务暂不可用，请稍后再试" } }, { status: 503 });
}

export async function GET(_request: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!TOKEN.test(token)) {
    return NextResponse.json({ error: { code: "report_share_unavailable", message: "链接不可用" } }, { status: 404 });
  }
  try {
    const response = await fetch(`${apiBase()}/api/v1/public/reports/${encodeURIComponent(token)}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      payload ?? { error: { code: "report_unavailable", message: "报告服务返回异常" } },
      { status: response.status, headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return failure();
  }
}

export async function POST(request: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!TOKEN.test(token)) {
    return NextResponse.json({ error: { code: "report_share_unavailable", message: "链接不可用" } }, { status: 404 });
  }
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  const password = typeof (body as { password?: unknown }).password === "string"
    ? (body as { password: string }).password.slice(0, 72)
    : null;
  try {
    const response = await fetch(`${apiBase()}/api/v1/public/reports/${encodeURIComponent(token)}/access`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ password }),
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      payload ?? { error: { code: "report_unavailable", message: "报告服务返回异常" } },
      { status: response.status, headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return failure();
  }
}
