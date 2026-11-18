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

function ids(url: URL) {
  const engineId = url.searchParams.get("engine_id") ?? "";
  const entryId = url.searchParams.get("entry_id") ?? "";
  return { engineId, entryId };
}

export async function GET(request: Request) {
  const auth = await session();
  if ("error" in auth) return auth.error;
  const url = new URL(request.url);
  const kind = url.searchParams.get("kind");
  const { engineId } = ids(url);
  const page = Math.max(1, Number(url.searchParams.get("page")) || 1);
  const pageSize = Math.min(100, Math.max(1, Number(url.searchParams.get("page_size")) || 20));
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  const path = kind === "engines" ? `/api/v1/engines?${params}`
    : kind === "entries" && uuid.test(engineId) ? `/api/v1/engines/${engineId}/entries?${params}` : null;
  if (!path) return NextResponse.json({ error: { code: "validation_error", message: "平台或入口参数无效" } }, { status: 400 });
  try { return NextResponse.json(await backendRequest(path as `/api/v1/${string}`, auth.token)); }
  catch (error) { return failure(error); }
}

export async function POST(request: Request) {
  const auth = await session();
  if ("error" in auth) return auth.error;
  const url = new URL(request.url);
  const kind = url.searchParams.get("kind");
  const { engineId, entryId } = ids(url);
  const path = kind === "engine" ? "/api/v1/engines"
    : kind === "entry" && uuid.test(engineId) ? `/api/v1/engines/${engineId}/entries`
    : kind === "test" && uuid.test(engineId) && uuid.test(entryId)
      ? `/api/v1/engines/${engineId}/entries/${entryId}/test-connection`
    : kind === "verify" && uuid.test(engineId) && uuid.test(entryId)
      ? `/api/v1/engines/${engineId}/entries/${entryId}/verify` : null;
  if (!path) return NextResponse.json({ error: { code: "validation_error", message: "平台或入口参数无效" } }, { status: 400 });
  const body = kind === "test" ? undefined : await request.json().catch(() => null);
  if (kind !== "test" && (!body || typeof body !== "object" || Array.isArray(body))) {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  try {
    return NextResponse.json(await backendRequest(path as `/api/v1/${string}`, auth.token, {
      method: "POST", ...(body ? { body: JSON.stringify(body) } : {}),
    }), { status: kind === "test" || kind === "verify" ? 200 : 201 });
  } catch (error) { return failure(error); }
}

export async function PATCH(request: Request) {
  const auth = await session();
  if ("error" in auth) return auth.error;
  const { engineId, entryId } = ids(new URL(request.url));
  if (!uuid.test(engineId) || !uuid.test(entryId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "入口 ID 无效" } }, { status: 400 });
  }
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  try {
    return NextResponse.json(await backendRequest(`/api/v1/engines/${engineId}/entries/${entryId}`, auth.token, {
      method: "PATCH", body: JSON.stringify(body),
    }));
  } catch (error) { return failure(error); }
}

export async function DELETE(request: Request) {
  const auth = await session();
  if ("error" in auth) return auth.error;
  const url = new URL(request.url);
  const kind = url.searchParams.get("kind");
  const { engineId, entryId } = ids(url);
  const path = kind === "engine" && uuid.test(engineId)
    ? `/api/v1/engines/${engineId}`
    : kind === "entry" && uuid.test(engineId) && uuid.test(entryId)
      ? `/api/v1/engines/${engineId}/entries/${entryId}` : null;
  if (!path) return NextResponse.json({ error: { code: "validation_error", message: "平台或入口参数无效" } }, { status: 400 });
  try {
    return NextResponse.json(await backendRequest(path as `/api/v1/${string}`, auth.token, { method: "DELETE" }));
  } catch (error) { return failure(error); }
}

