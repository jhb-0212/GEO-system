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

async function session() {
  const token = await getSessionToken();
  if (!token || isMockMode() && token !== "demo") {
    return { error: NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 }) };
  }
  if (isMockMode()) {
    return { error: NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用真实接口" } }, { status: 400 }) };
  }
  return { token };
}

function projectIdOf(url: URL) {
  const projectId = url.searchParams.get("project_id") ?? "";
  return uuid.test(projectId) ? projectId : "";
}

export async function GET(request: Request) {
  const auth = await session();
  if ("error" in auth) return auth.error;
  const url = new URL(request.url);
  const projectId = projectIdOf(url);
  if (!projectId) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  const kind = url.searchParams.get("kind");
  const path = kind === "status" ? `/api/v1/projects/${projectId}/stats/industry`
    : kind === "presets" ? `/api/v1/projects/${projectId}/industry-presets` : null;
  if (!path) return NextResponse.json({ error: { code: "validation_error", message: "参数无效" } }, { status: 400 });
  try {
    return NextResponse.json(await backendRequest(path as `/api/v1/${string}`, auth.token));
  } catch (error) { return failure(error); }
}

export async function POST(request: Request) {
  const auth = await session();
  if ("error" in auth) return auth.error;
  const url = new URL(request.url);
  const projectId = projectIdOf(url);
  if (!projectId) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  const kind = url.searchParams.get("kind");
  if (kind !== "preview" && kind !== "apply") {
    return NextResponse.json({ error: { code: "validation_error", message: "参数无效" } }, { status: 400 });
  }
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  try {
    return NextResponse.json(await backendRequest(
      `/api/v1/projects/${projectId}/onboarding/${kind}` as `/api/v1/${string}`,
      auth.token,
      { method: "POST", body: JSON.stringify(body) },
    ));
  } catch (error) { return failure(error); }
}
