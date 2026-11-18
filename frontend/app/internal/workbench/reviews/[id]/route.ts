import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { updateMockReview } from "@/lib/workbench/mock";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * 兼容旧的内容审核入口。
 *
 * 真实模式下直接调后端 `POST /content-versions/{id}/review`：
 * 之前这里固定返回 501 contract_pending，「通过/驳回」在工作台里必然失败。
 * 后端接口其实早已可用，缺的只是这条转发。审核状态到 decision 的映射保持与演示模式一致。
 */
export async function PATCH(request: Request, context: RouteContext<"/internal/workbench/reviews/[id]">) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  const { id } = await context.params;
  const body = await request.json().catch(() => ({}));
  if (body.status !== "已通过" && body.status !== "已驳回") {
    return NextResponse.json({ error: { code: "validation_error", message: "无效的审核状态" } }, { status: 400 });
  }
  if (isMockMode()) {
    if (session !== "demo") return NextResponse.json({ error: { code: "unauthorized", message: "演示会话无效" } }, { status: 401 });
    const review = updateMockReview(id, body.status);
    if (!review) return NextResponse.json({ error: { code: "not_found", message: "审核项不存在" } }, { status: 404 });
    return NextResponse.json({ data: review });
  }

  const projectId = new URL(request.url).searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请提供有效项目" } }, { status: 400 });
  }
  if (!uuid.test(id)) {
    return NextResponse.json({ error: { code: "validation_error", message: "内容版本 ID 无效" } }, { status: 400 });
  }
  try {
    const result = await backendRequest<{ review_id: string; decision: string }>(
      `/api/v1/projects/${projectId}/content-versions/${id}/review`,
      session,
      {
        method: "POST",
        body: JSON.stringify({
          decision: body.status === "已通过" ? "approved" : "rejected",
          comment: typeof body.comment === "string" ? body.comment : null,
        }),
      },
    );
    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
