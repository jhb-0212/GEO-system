import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

const PASS_THROUGH = ["round_id", "engine_id", "question_id", "start_at", "end_at", "answer_kind", "question_type"];

/** 诊断报告只读透传：筛选参数原样带给后端，前端不重算任何分项。 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不展示诊断报告" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }

  const query = new URLSearchParams();
  for (const key of PASS_THROUGH) {
    const value = search.get(key);
    if (value) query.set(key, value);
  }

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/diagnosis-report${query.size ? `?${query}` : ""}`, apiBase()),
      { headers: { Authorization: `Bearer ${session}` }, cache: "no-store" },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "diagnosis_failed", message: "报告生成失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
