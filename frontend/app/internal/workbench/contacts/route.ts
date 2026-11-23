import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

async function forward(request: Request, method: "GET" | "POST") {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不读写对外渠道" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }

  const suffix = method === "GET" && search.get("include_inactive") ? "?include_inactive=true" : "";
  try {
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/contacts${suffix}`, apiBase()), {
      method,
      headers: { Authorization: `Bearer ${session}`, ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      body: method === "POST" ? await request.text() : undefined,
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "contact_failed", message: "渠道操作失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}

export async function GET(request: Request) {
  return forward(request, "GET");
}

export async function POST(request: Request) {
  return forward(request, "POST");
}
