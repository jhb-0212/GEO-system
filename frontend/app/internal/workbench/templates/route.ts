import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

/**
 * 内容模板：列表 + 新建 + 改模板 + 按模板生成草稿。
 * 槽位解析、缺槽校验、正文渲染全在后端做，这里只做鉴权与转发，
 * 避免前端与后端各有一套占位符规则。
 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不展示内容模板" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }
  const page = search.get("page") ?? "1";
  const includeInactive = search.get("include_inactive") === "true" ? "&include_inactive=true" : "";

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/content-templates?page=${encodeURIComponent(page)}&page_size=20${includeInactive}`, apiBase()),
      { headers: { Authorization: `Bearer ${session}` }, cache: "no-store" },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "template_failed", message: "模板加载失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}

export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不能建模板" } }, { status: 400 });

  const search = new URL(request.url).searchParams;
  const projectId = search.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }
  const templateId = search.get("template_id");
  const action = search.get("action");

  let target: string;
  let method = "POST";
  if (templateId && !uuid.test(templateId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "模板 id 无效" } }, { status: 400 });
  }
  if (templateId && action === "generate") {
    target = `/api/v1/projects/${projectId}/content-templates/${templateId}/generate`;
  } else if (templateId) {
    target = `/api/v1/projects/${projectId}/content-templates/${templateId}`;
    method = "PATCH";
  } else {
    target = `/api/v1/projects/${projectId}/content-templates`;
  }

  try {
    const response = await fetch(new URL(target, apiBase()), {
      method,
      headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
      body: await request.text(),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "template_failed", message: "模板操作失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
