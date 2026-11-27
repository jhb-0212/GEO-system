import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/**
 * 起草模型配置的 BFF 转发（GET 读 / PUT 存）。
 *
 * Key 是加密落库的，后端只回显「有没有存」和指纹；这里也不做任何日志打印，
 * 免得 Key 在应用日志里出现第二份。
 */
async function forward(request: Request, method: "GET" | "PUT", body?: string) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不改起草模型配置" } }, { status: 400 });

  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });

  try {
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/company-profile/draft-model`, apiBase()), {
      method,
      headers: { Authorization: `Bearer ${session}`, ...(body ? { "Content-Type": "application/json" } : {}) },
      body,
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "company_draft_model_failed", message: "起草模型配置失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}

export async function GET(request: Request) {
  return forward(request, "GET");
}

export async function PUT(request: Request) {
  const body = await request.text();
  return forward(request, "PUT", body || "{}");
}
