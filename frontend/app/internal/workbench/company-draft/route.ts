import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/**
 * 一键填表的 BFF 转发。
 *
 * 只读接口：后端返回建议字段，不落库；演示模式下也直接拒，
 * 免得前端拿到一份「看起来像真数据」的建议去保存。
 */
export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不生成企业档案草稿" } }, { status: 400 });

  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  const prefer = url.searchParams.get("prefer") === "rule" ? "rule" : "auto";
  if (!uuid.test(projectId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/company-profile/draft?prefer=${prefer}`, apiBase()),
      { method: "POST", headers: { Authorization: `Bearer ${session}` }, cache: "no-store" },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "company_draft_failed", message: "一键填表失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
