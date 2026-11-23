import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

async function projectIdFrom(request: Request): Promise<string | null> {
  const projectId = new URL(request.url).searchParams.get("project_id") ?? "";
  return uuid.test(projectId) ? projectId : null;
}

async function forward(request: Request, method: "GET" | "POST") {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不读写真实资质" } }, { status: 400 });

  const projectId = await projectIdFrom(request);
  if (!projectId) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });

  const query = new URL(request.url).searchParams.get("include_inactive");
  const suffix = method === "GET" && query ? `?include_inactive=${encodeURIComponent(query)}` : "";
  try {
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/certifications${suffix}`, apiBase()), {
      method,
      headers: { Authorization: `Bearer ${session}`, ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      body: method === "POST" ? await request.text() : undefined,
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "certification_failed", message: "资质操作失败" } }, { status: response.status });
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
