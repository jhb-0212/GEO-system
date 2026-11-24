import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function failure(error: unknown) {
  if (error instanceof BackendError) {
    return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
  }
  return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
}

async function context(request: Request) {
  const token = await getSessionToken();
  if (!token || isMockMode() && token !== "demo") {
    return { error: NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 }) };
  }
  if (isMockMode()) {
    return { error: NextResponse.json({ error: { code: "mock_only", message: "演示模式不修改名册" } }, { status: 400 }) };
  }
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return { error: NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 }) };
  }
  return { token, url, projectId };
}

export async function GET(request: Request) {
  const ctx = await context(request);
  if ("error" in ctx) return ctx.error;
  try {
    return NextResponse.json(await backendRequest(
      `/api/v1/projects/${ctx.projectId}/organization-members` as `/api/v1/${string}`, ctx.token,
    ));
  } catch (error) { return failure(error); }
}

export async function POST(request: Request) {
  const ctx = await context(request);
  if ("error" in ctx) return ctx.error;
  const kind = ctx.url.searchParams.get("kind");
  try {
    if (kind === "sync") {
      return NextResponse.json(await backendRequest(
        `/api/v1/projects/${ctx.projectId}/organization-members/sync` as `/api/v1/${string}`,
        ctx.token,
        { method: "POST" },
      ));
    }
    const body = await request.json().catch(() => null) as Record<string, unknown> | null;
    if (!body || typeof body !== "object" || typeof body.username !== "string" || !body.username.trim()) {
      return NextResponse.json({ error: { code: "validation_error", message: "请填写工作账号" } }, { status: 400 });
    }
    return NextResponse.json(await backendRequest(
      `/api/v1/projects/${ctx.projectId}/organization-members` as `/api/v1/${string}`,
      ctx.token,
      { method: "POST", body: JSON.stringify({ username: body.username.trim() }) },
    ));
  } catch (error) { return failure(error); }
}

export async function DELETE(request: Request) {
  const ctx = await context(request);
  if ("error" in ctx) return ctx.error;
  const userId = ctx.url.searchParams.get("user_id") ?? "";
  if (!uuid.test(userId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "成员无效" } }, { status: 400 });
  }
  try {
    return NextResponse.json(await backendRequest(
      `/api/v1/projects/${ctx.projectId}/organization-members/${userId}` as `/api/v1/${string}`,
      ctx.token,
      { method: "DELETE" },
    ));
  } catch (error) { return failure(error); }
}
