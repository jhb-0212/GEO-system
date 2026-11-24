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

export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token || isMockMode() && token !== "demo") {
    return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  }
  if (isMockMode()) {
    return NextResponse.json({ error: { code: "mock_only", message: "演示模式不创建真实项目" } }, { status: 400 });
  }
  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  if (typeof body.code !== "string" || typeof body.name !== "string") {
    return NextResponse.json({ error: { code: "validation_error", message: "项目编码与名称必填" } }, { status: 400 });
  }
  if (typeof body.organization_id !== "string" || !uuid.test(body.organization_id)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择客户" } }, { status: 400 });
  }
  try {
    return NextResponse.json(await backendRequest(
      "/api/v1/projects" as `/api/v1/${string}`,
      token,
      { method: "POST", body: JSON.stringify({ code: body.code, name: body.name, organization_id: body.organization_id }) },
    ), { status: 201 });
  } catch (error) { return failure(error); }
}
