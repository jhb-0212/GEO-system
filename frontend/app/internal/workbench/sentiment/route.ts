import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/** 情绪统计：`view=summary|items` 两条只读出口，原文一律由后端回读引用表。 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不展示情绪统计" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  const view = search.get("view") ?? "summary";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }

  const query = new URLSearchParams();
  for (const key of ["polarity", "sort", "page", "page_size"]) {
    const value = search.get(key);
    if (value) query.set(key, value);
  }

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/sentiment/${view === "items" ? "items" : "summary"}${query.size ? `?${query}` : ""}`, apiBase()),
      { headers: { Authorization: `Bearer ${session}` }, cache: "no-store" },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "sentiment_failed", message: "情绪统计失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}

/** 人工标注：只写判断，不改引用本身。 */
export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不能标注" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  const citationId = search.get("citation_id") ?? "";
  if (!uuid.test(projectId) || !uuid.test(citationId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "项目或引文不合法" } }, { status: 400 });
  }

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/sentiment/${citationId}/label`, apiBase()),
      {
        method: "POST",
        headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
        body: await request.text(),
        cache: "no-store",
      },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "sentiment_label_failed", message: "标注失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
