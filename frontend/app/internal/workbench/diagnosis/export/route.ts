import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/** 诊断报告 CSV：筛选参数原样转发，导出与页面同一口径。 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不导出" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }

  const query = new URLSearchParams();
  for (const key of ["round_id", "engine_id", "question_id", "start_at", "end_at", "answer_kind", "question_type"]) {
    const value = search.get(key);
    if (value) query.set(key, value);
  }

  try {
    const upstream = await fetch(
      new URL(`/api/v1/projects/${projectId}/diagnosis-report/export${query.size ? `?${query}` : ""}`, apiBase()),
      { headers: { Authorization: `Bearer ${session}` }, cache: "no-store" },
    );
    if (!upstream.ok) {
      const payload = await upstream.json().catch(() => null);
      return NextResponse.json(payload ?? { error: { code: "export_failed", message: "导出失败" } }, { status: upstream.status });
    }
    return new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "text/csv; charset=utf-8",
        "Content-Disposition": upstream.headers.get("content-disposition") ?? 'attachment; filename="diagnosis-report.csv"',
      },
    });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
