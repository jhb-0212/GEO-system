import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(request: Request, context: RouteContext<"/internal/workbench/evidence/[id]">) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不提供证据文件" } }, { status: 400 });
  const { id } = await context.params;
  const projectId = new URL(request.url).searchParams.get("project_id") ?? "";
  if (!uuid.test(id) || !uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "项目或证据 ID 无效" } }, { status: 400 });
  }
  try {
    const base = process.env.GEO_API_URL || (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
    const response = await fetch(`${base.replace(/\/$/, "")}/api/v1/projects/${projectId}/evidence/${id}/download`, {
      headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ error: { code: "upstream_error", message: "证据下载失败" } }));
      return NextResponse.json(payload, { status: response.status });
    }
    return new Response(response.body, {
      status: 200,
      headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream",
        "Content-Disposition": response.headers.get("Content-Disposition") ?? `attachment; filename="evidence-${id}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
