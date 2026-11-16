import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不下载文件" } }, { status: 400 });

  const { id } = await context.params;
  if (!uuid.test(id)) return NextResponse.json({ error: { code: "validation_error", message: "素材 ID 无效" } }, { status: 400 });
  const projectId = new URL(request.url).searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });

  const apiBase = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
  try {
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/materials/${id}/download`, apiBase), {
      headers: { Authorization: `Bearer ${session}` },
      cache: "no-store",
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      return NextResponse.json(payload ?? { error: { code: "download_failed", message: "下载失败" } }, { status: response.status });
    }
    return new Response(response.body, {
      status: 200,
      headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream",
        "Content-Disposition": response.headers.get("Content-Disposition") ?? "attachment",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
