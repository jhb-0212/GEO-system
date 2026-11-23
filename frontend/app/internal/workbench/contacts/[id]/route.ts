import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

async function forward(request: Request, method: "PATCH" | "DELETE") {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不读写对外渠道" } }, { status: 400 });

  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  const contactId = url.pathname.split("/").filter(Boolean).pop() ?? "";
  if (!uuid.test(projectId) || !uuid.test(contactId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "项目或渠道记录不合法" } }, { status: 400 });
  }

  try {
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/contacts/${contactId}`, apiBase()), {
      method,
      headers: { Authorization: `Bearer ${session}`, ...(method === "PATCH" ? { "Content-Type": "application/json" } : {}) },
      body: method === "PATCH" ? await request.text() : undefined,
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

export async function PATCH(request: Request) {
  return forward(request, "PATCH");
}

export async function DELETE(request: Request) {
  return forward(request, "DELETE");
}
