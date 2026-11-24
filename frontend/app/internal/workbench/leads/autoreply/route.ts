import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/**
 * 留言固定话术：GET 读配置、PUT 改开关与话术。
 *
 * 话术是**模板句**，不是生成式对话：前端不给「问一句答一句」的入口，
 * 只给一个开关和一段可编辑的固定文本，避免又变回数字员工。
 */
async function proxy(request: Request, method: "GET" | "PUT") {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不配置自动回复" } }, { status: 400 });

  const projectId = new URL(request.url).searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }

  try {
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/leads/autoreply`, apiBase()), {
      method,
      headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
      body: method === "PUT" ? await request.text() : undefined,
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "lead_autoreply_failed", message: "自动回复配置失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}

export async function GET(request: Request) {
  return proxy(request, "GET");
}

export async function PUT(request: Request) {
  return proxy(request, "PUT");
}
