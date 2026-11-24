import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/** 负面标注 → 纠正批次：把一条人工确认的负面引用变成一篇待审纠正稿。 */
export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不能建纠正批次" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  const citationId = search.get("citation_id") ?? "";
  if (!uuid.test(projectId) || !uuid.test(citationId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "项目或引文不合法" } }, { status: 400 });
  }

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/sentiment/${citationId}/corrective-batch`, apiBase()),
      {
        method: "POST",
        headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
        body: await request.text(),
        cache: "no-store",
      },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "corrective_batch_failed", message: "纠正批次创建失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 201 });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
