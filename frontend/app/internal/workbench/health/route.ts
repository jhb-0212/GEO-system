import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

function failure(message: string, code: string, status: number) {
  return NextResponse.json({ error: { code, message } }, { status });
}

/** B5 体检：GET 回看历史（带 run_id 取单次快照），POST 跑一次新体检。 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不展示体检数据", "mock_only", 400);

  const params = new URL(request.url).searchParams;
  const projectId = params.get("project_id") ?? "";
  const runId = params.get("run_id") ?? "";
  if (!uuid.test(projectId)) return failure("请选择有效项目", "validation_error", 400);
  if (runId && !uuid.test(runId)) return failure("体检记录无效", "validation_error", 400);

  const path = runId
    ? `/api/v1/projects/${projectId}/health-checks/${runId}`
    : `/api/v1/projects/${projectId}/health-checks`;
  try {
    const response = await fetch(new URL(path, apiBase()), {
      headers: { Authorization: `Bearer ${session}` }, cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "health_failed", message: "体检数据加载失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}

export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不能跑体检", "mock_only", 400);

  const projectId = new URL(request.url).searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) return failure("请选择有效项目", "validation_error", 400);

  try {
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/health-checks`, apiBase()), {
      method: "POST",
      headers: { Authorization: `Bearer ${session}` },
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "health_run_failed", message: "体检执行失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}
