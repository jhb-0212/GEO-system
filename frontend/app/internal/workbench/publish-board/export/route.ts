import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/** CSV 导出代理：转发后端流并保留附件头，权限与行数上限都由后端判定。 */
async function proxyExport(url: URL, projectId: string, path: string) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不导出" } }, { status: 400 });
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }

  try {
    const upstream = await fetch(new URL(path, apiBase()), {
      headers: { Authorization: `Bearer ${session}` },
      cache: "no-store",
    });
    if (!upstream.ok) {
      const payload = await upstream.json().catch(() => null);
      return NextResponse.json(payload ?? { error: { code: "export_failed", message: "导出失败" } }, { status: upstream.status });
    }
    return new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "text/csv; charset=utf-8",
        "Content-Disposition": upstream.headers.get("content-disposition") ?? 'attachment; filename="export.csv"',
      },
    });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  return proxyExport(url, url.searchParams.get("project_id") ?? "", `/api/v1/projects/${url.searchParams.get("project_id")}/publish-board/export`);
}
