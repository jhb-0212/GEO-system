import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const moduleType = /^(home|services|news|download|poster|card)$/;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

function failure(message: string, code: string, status: number) {
  return NextResponse.json({ error: { code, message } }, { status });
}

/** K8 微站配置：GET 会触发后端自动建站（幂等），PATCH 改站点信息或单个模块。 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不展示微站配置", "mock_only", 400);

  const projectId = new URL(request.url).searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) return failure("请选择有效项目", "validation_error", 400);

  try {
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/site`, apiBase()), {
      headers: { Authorization: `Bearer ${session}` }, cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "site_failed", message: "微站配置加载失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}

export async function PATCH(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不能修改微站配置", "mock_only", 400);

  const params = new URL(request.url).searchParams;
  const projectId = params.get("project_id") ?? "";
  const type = params.get("module_type") ?? "";
  if (!uuid.test(projectId)) return failure("请选择有效项目", "validation_error", 400);
  if (type && !moduleType.test(type)) return failure("模块类型无效", "validation_error", 400);

  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") return failure("请求数据无效", "validation_error", 400);

  const path = type ? `/api/v1/projects/${projectId}/site/modules/${type}` : `/api/v1/projects/${projectId}/site`;
  try {
    const response = await fetch(new URL(path, apiBase()), {
      method: "PATCH",
      headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "site_update_failed", message: "微站配置保存失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}
