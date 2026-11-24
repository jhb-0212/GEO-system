import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

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

export async function GET(request: Request) {
  const auth = await session();
  if ("error" in auth) return auth.error;
  const url = new URL(request.url);
  const q = url.searchParams.get("q");
  const path = q ? `/api/v1/organizations?q=${encodeURIComponent(q)}` : "/api/v1/organizations";
  try {
    return NextResponse.json(await backendRequest(path as `/api/v1/${string}`, auth.token));
  } catch (error) { return failure(error); }
}

export async function POST(request: Request) {
  const auth = await session();
  if ("error" in auth) return auth.error;
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  try {
    return NextResponse.json(await backendRequest(
      "/api/v1/organizations" as `/api/v1/${string}`,
      auth.token,
      { method: "POST", body: JSON.stringify(body) },
    ));
  } catch (error) { return failure(error); }
}
