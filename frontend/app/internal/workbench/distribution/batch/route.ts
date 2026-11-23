import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/** 重检 / 标记已投喂：只转发动作，是否放行由后端预检判定。 */
export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不能操作批次" } }, { status: 400 });

  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  const batchId = url.searchParams.get("batch_id") ?? "";
  const action = url.searchParams.get("action") ?? "";
  if (!uuid.test(projectId) || !uuid.test(batchId) || !["recheck", "dispatch"].includes(action)) {
    return NextResponse.json({ error: { code: "validation_error", message: "项目、批次或动作不合法" } }, { status: 400 });
  }

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/distribution-batches/${batchId}/${action}`, apiBase()),
      { method: "POST", headers: { Authorization: `Bearer ${session}` }, cache: "no-store" },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "batch_action_failed", message: "操作失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
