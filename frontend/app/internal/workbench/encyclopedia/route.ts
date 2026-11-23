import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

function failure(message: string, code: string, status: number) {
  return NextResponse.json({ error: { code, message } }, { status });
}

/** K4 百科词条：GET 列表/详情 · POST 新建/提交/审/登记外链 · PATCH 改稿。 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不展示百科词条", "mock_only", 400);

  const params = new URL(request.url).searchParams;
  const projectId = params.get("project_id") ?? "";
  const entryId = params.get("entry_id") ?? "";
  if (!uuid.test(projectId)) return failure("请选择有效项目", "validation_error", 400);
  if (entryId && !uuid.test(entryId)) return failure("词条无效", "validation_error", 400);

  const path = entryId
    ? `/api/v1/projects/${projectId}/encyclopedia-entries/${entryId}`
    : `/api/v1/projects/${projectId}/encyclopedia-entries`;

  try {
    const response = await fetch(new URL(path, apiBase()), {
      headers: { Authorization: `Bearer ${session}` }, cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "encyclopedia_failed", message: "百科词条加载失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}

export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不能改百科词条", "mock_only", 400);

  const params = new URL(request.url).searchParams;
  const projectId = params.get("project_id") ?? "";
  const entryId = params.get("entry_id") ?? "";
  const action = params.get("action") ?? "";
  if (!uuid.test(projectId)) return failure("请选择有效项目", "validation_error", 400);

  try {
    if (!entryId) {
      const body = await request.json().catch(() => null);
      if (!body || typeof body !== "object") return failure("请求数据无效", "validation_error", 400);
      const response = await fetch(new URL(`/api/v1/projects/${projectId}/encyclopedia-entries`, apiBase()), {
        method: "POST",
        headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        return NextResponse.json(payload ?? { error: { code: "encyclopedia_create_failed", message: "新建词条失败" } }, { status: response.status });
      }
      return NextResponse.json(payload, { status: 201 });
    }

    if (!uuid.test(entryId)) return failure("词条无效", "validation_error", 400);
    if (!["submit", "review", "publication"].includes(action)) {
      return failure("动作无效", "validation_error", 400);
    }
    const body = action === "submit" ? undefined : await request.json().catch(() => null);
    if (action !== "submit" && (!body || typeof body !== "object")) {
      return failure("请求数据无效", "validation_error", 400);
    }
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/encyclopedia-entries/${entryId}/${action}`, apiBase()),
      {
        method: "POST",
        headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
        cache: "no-store",
      },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "encyclopedia_action_failed", message: "操作失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}

export async function PATCH(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不能改百科词条", "mock_only", 400);

  const params = new URL(request.url).searchParams;
  const projectId = params.get("project_id") ?? "";
  const entryId = params.get("entry_id") ?? "";
  if (!uuid.test(projectId) || !uuid.test(entryId)) return failure("参数无效", "validation_error", 400);

  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") return failure("请求数据无效", "validation_error", 400);

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/encyclopedia-entries/${entryId}`, apiBase()),
      {
        method: "PATCH",
        headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "encyclopedia_update_failed", message: "保存失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}
