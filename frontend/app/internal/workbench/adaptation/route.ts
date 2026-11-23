import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/**
 * 渠道改编：派生、血缘列表、项目级一致性清单、跟版。
 * 视角切换用 view 参数，避免为一个只读页再开四条路由。
 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不展示渠道改编" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }
  const view = search.get("view") ?? "derivations";
  const itemId = search.get("item_id") ?? "";

  let target: string;
  if (view === "consistency") {
    const staleOnly = search.get("stale_only") === "true" ? "&stale_only=true" : "";
    target = `/api/v1/projects/${projectId}/contents/derivations?page=1&page_size=100${staleOnly}`;
  } else {
    if (!uuid.test(itemId)) {
      return NextResponse.json({ error: { code: "validation_error", message: "请选择要改编的母稿" } }, { status: 400 });
    }
    target = `/api/v1/projects/${projectId}/contents/${itemId}/derivations`;
  }

  try {
    const response = await fetch(new URL(target, apiBase()), {
      headers: { Authorization: `Bearer ${session}` }, cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "derivation_failed", message: "改编记录加载失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}

export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不能改编" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  const itemId = search.get("item_id") ?? "";
  const action = search.get("action") ?? "derive";
  if (!uuid.test(projectId) || !uuid.test(itemId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "参数不完整" } }, { status: 400 });
  }

  let target: string;
  let body = await request.text();
  if (action === "sync") {
    const derivationId = search.get("derivation_id") ?? "";
    if (!uuid.test(derivationId)) {
      return NextResponse.json({ error: { code: "validation_error", message: "改编记录 id 无效" } }, { status: 400 });
    }
    target = `/api/v1/projects/${projectId}/contents/${itemId}/derivations/${derivationId}/sync`;
    body = "{}";
  } else {
    target = `/api/v1/projects/${projectId}/contents/${itemId}/derive`;
  }

  try {
    const response = await fetch(new URL(target, apiBase()), {
      method: "POST",
      headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "derivation_failed", message: "改编操作失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
