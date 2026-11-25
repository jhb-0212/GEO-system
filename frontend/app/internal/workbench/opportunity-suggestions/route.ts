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

export async function GET(request: Request) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用机会建议接口" } }, { status: 400 });
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  const params = new URLSearchParams();
  for (const key of ["status", "rule_code", "page", "page_size"]) {
    const value = url.searchParams.get(key);
    if (value) params.set(key, value);
  }
  try {
    return NextResponse.json(await backendRequest(
      `/api/v1/projects/${projectId}/opportunities/suggestions?${params}` as `/api/v1/${string}`, token,
    ));
  } catch (error) {
    return failure(error);
  }
}

export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用机会建议接口" } }, { status: 400 });
  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  const projectId = typeof body?.project_id === "string" ? body.project_id : "";
  const action = typeof body?.action === "string" ? body.action : "";
  if (!uuid.test(projectId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  const base = `/api/v1/projects/${projectId}/opportunities/suggestions` as const;
  try {
    if (action === "generate") {
      return NextResponse.json(await backendRequest(`${base}/generate` as `/api/v1/${string}`, token, {
        method: "POST", body: JSON.stringify({}),
      }));
    }
    const suggestionId = typeof body?.suggestion_id === "string" ? body.suggestion_id : "";
    if (!uuid.test(suggestionId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效建议" } }, { status: 400 });
    if (action === "accept") {
      return NextResponse.json(await backendRequest(`${base}/${suggestionId}/accept` as `/api/v1/${string}`, token, {
        method: "POST", body: JSON.stringify({ note: body?.note }),
      }));
    }
    if (action === "dismiss") {
      return NextResponse.json(await backendRequest(`${base}/${suggestionId}/dismiss` as `/api/v1/${string}`, token, {
        method: "POST", body: JSON.stringify({ note: body?.note }),
      }));
    }
    return NextResponse.json({ error: { code: "validation_error", message: "未知机会建议操作" } }, { status: 400 });
  } catch (error) {
    return failure(error);
  }
}
