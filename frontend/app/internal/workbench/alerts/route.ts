import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function failure(error: unknown) {
  if (error instanceof BackendError) {
    return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
  }
  return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
}

export async function GET(request: Request) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用预警接口" } }, { status: 400 });
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  const kind = url.searchParams.get("kind") ?? "events";
  const params = new URLSearchParams();
  for (const key of ["status", "code", "page", "page_size"]) {
    const value = url.searchParams.get(key);
    if (value) params.set(key, value);
  }
  try {
    const suffix = kind === "rules" ? "rules" : `events?${params}`;
    return NextResponse.json(await backendRequest(`/api/v1/projects/${projectId}/alerts/${suffix}` as `/api/v1/${string}`, token));
  } catch (error) {
    return failure(error);
  }
}

export async function PATCH(request: Request) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用预警接口" } }, { status: 400 });
  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  const projectId = typeof body?.project_id === "string" ? body.project_id : "";
  const ruleId = typeof body?.rule_id === "string" ? body.rule_id : "";
  if (!uuid.test(projectId) || !uuid.test(ruleId)) return NextResponse.json({ error: { code: "validation_error", message: "项目或规则无效" } }, { status: 400 });
  const payload: Record<string, unknown> = {};
  for (const key of ["is_enabled", "severity", "thresholds"]) if (body?.[key] !== undefined) payload[key] = body[key];
  try {
    return NextResponse.json(await backendRequest(`/api/v1/projects/${projectId}/alerts/rules/${ruleId}` as `/api/v1/${string}`, token, {
      method: "PATCH", body: JSON.stringify(payload),
    }));
  } catch (error) {
    return failure(error);
  }
}

export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用预警接口" } }, { status: 400 });
  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  const projectId = typeof body?.project_id === "string" ? body.project_id : "";
  const action = typeof body?.action === "string" ? body.action : "";
  if (!uuid.test(projectId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  const base = `/api/v1/projects/${projectId}/alerts` as const;
  try {
    if (action === "evaluate") {
      return NextResponse.json(await backendRequest(`${base}/evaluate` as `/api/v1/${string}`, token, {
        method: "POST", body: JSON.stringify({}),
      }));
    }
    const eventId = typeof body?.event_id === "string" ? body.event_id : "";
    if (!uuid.test(eventId)) return NextResponse.json({ error: { code: "validation_error", message: "请选择有效预警事件" } }, { status: 400 });
    if (action === "ack") {
      return NextResponse.json(await backendRequest(`${base}/events/${eventId}/ack` as `/api/v1/${string}`, token, {
        method: "POST", body: JSON.stringify({ note: body?.note }),
      }));
    }
    if (action === "resolve") {
      return NextResponse.json(await backendRequest(`${base}/events/${eventId}/resolve` as `/api/v1/${string}`, token, {
        method: "POST", body: JSON.stringify({}),
      }));
    }
    return NextResponse.json({ error: { code: "validation_error", message: "未知预警操作" } }, { status: 400 });
  } catch (error) {
    return failure(error);
  }
}
