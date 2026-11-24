import { NextResponse } from "next/server";

import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

function failure(error: unknown) {
  if (error instanceof BackendError) {
    return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
  }
  return NextResponse.json(
    { error: { code: "backend_unavailable", message: "无法连接后端" } },
    { status: 503 },
  );
}

async function token() {
  const session = await getSessionToken();
  if (!session || (isMockMode() && session !== "demo")) {
    return { error: NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 }) };
  }
  if (isMockMode()) {
    return { error: NextResponse.json({ error: { code: "mock_only", message: "演示模式不保存真实配置" } }, { status: 400 }) };
  }
  return { token: session };
}

export async function GET() {
  const auth = await token();
  if ("error" in auth) return auth.error;
  try {
    return NextResponse.json(await backendRequest("/api/v1/media-matrix/config", auth.token));
  } catch (error) {
    return failure(error);
  }
}

export async function PUT(request: Request) {
  const auth = await token();
  if ("error" in auth) return auth.error;
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  try {
    return NextResponse.json(await backendRequest("/api/v1/media-matrix/config", auth.token, {
      method: "PUT",
      body: JSON.stringify(body),
    }));
  } catch (error) {
    return failure(error);
  }
}

export async function DELETE() {
  const auth = await token();
  if ("error" in auth) return auth.error;
  try {
    return NextResponse.json(await backendRequest("/api/v1/media-matrix/config", auth.token, { method: "DELETE" }));
  } catch (error) {
    return failure(error);
  }
}
