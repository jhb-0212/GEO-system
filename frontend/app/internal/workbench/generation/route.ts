import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

function failure(message: string, code: string, status: number) {
  return NextResponse.json({ error: { code, message } }, { status });
}

/** G1/G2 生成批次：GET（列表/详情/导出）· POST（建批/跑批）· PATCH（审稿标记）。 */
export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不展示生成批次", "mock_only", 400);

  const params = new URL(request.url).searchParams;
  const projectId = params.get("project_id") ?? "";
  const batchId = params.get("batch_id") ?? "";
  if (!uuid.test(projectId)) return failure("请选择有效项目", "validation_error", 400);
  if (batchId && !uuid.test(batchId)) return failure("批次无效", "validation_error", 400);

  const isExport = params.get("export") === "1";
  const path = batchId
    ? `/api/v1/projects/${projectId}/generation-batches/${batchId}${isExport ? "/export" : ""}`
    : `/api/v1/projects/${projectId}/generation-batches`;

  try {
    const response = await fetch(new URL(path, apiBase()), {
      headers: { Authorization: `Bearer ${session}` }, cache: "no-store",
    });
    if (isExport) {
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        return NextResponse.json(payload ?? { error: { code: "export_failed", message: "导出失败" } }, { status: response.status });
      }
      const body = await response.arrayBuffer();
      return new NextResponse(body, {
        status: 200,
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": response.headers.get("Content-Disposition") ?? 'attachment; filename="generation.csv"',
        },
      });
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "generation_failed", message: "生成批次加载失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}

export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不能建生成批次", "mock_only", 400);

  const params = new URL(request.url).searchParams;
  const projectId = params.get("project_id") ?? "";
  const batchId = params.get("batch_id") ?? "";
  if (!uuid.test(projectId)) return failure("请选择有效项目", "validation_error", 400);

  try {
    if (batchId) {
      if (!uuid.test(batchId)) return failure("批次无效", "validation_error", 400);
      const response = await fetch(
        new URL(`/api/v1/projects/${projectId}/generation-batches/${batchId}/run`, apiBase()),
        { method: "POST", headers: { Authorization: `Bearer ${session}` }, cache: "no-store" },
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        return NextResponse.json(payload ?? { error: { code: "generation_run_failed", message: "跑批失败" } }, { status: response.status });
      }
      return NextResponse.json(payload, { status: 200 });
    }

    const body = await request.json().catch(() => null);
    if (!body || typeof body !== "object") return failure("请求数据无效", "validation_error", 400);
    const response = await fetch(new URL(`/api/v1/projects/${projectId}/generation-batches`, apiBase()), {
      method: "POST",
      headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "generation_create_failed", message: "建批失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}

export async function PATCH(request: Request) {
  const session = await getSessionToken();
  if (!session) return failure("请先登录", "unauthorized", 401);
  if (isMockMode()) return failure("演示模式不能审稿", "mock_only", 400);

  const params = new URL(request.url).searchParams;
  const projectId = params.get("project_id") ?? "";
  const batchId = params.get("batch_id") ?? "";
  const itemId = params.get("item_id") ?? "";
  if (!uuid.test(projectId) || !uuid.test(batchId) || !uuid.test(itemId)) {
    return failure("参数无效", "validation_error", 400);
  }

  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") return failure("请求数据无效", "validation_error", 400);

  try {
    const response = await fetch(
      new URL(`/api/v1/projects/${projectId}/generation-batches/${batchId}/items/${itemId}`, apiBase()),
      {
        method: "PATCH",
        headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "generation_review_failed", message: "审稿失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: 200 });
  } catch {
    return failure("无法连接后端", "backend_unavailable", 503);
  }
}
