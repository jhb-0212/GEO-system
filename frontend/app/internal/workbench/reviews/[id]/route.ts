import { NextResponse } from "next/server";
import { updateMockReview } from "@/lib/workbench/mock";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

export async function PATCH(request: Request, context: RouteContext<"/internal/workbench/reviews/[id]">) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (!isMockMode()) {
    return NextResponse.json({ error: { code: "contract_pending", message: "审核操作等待后端接口联调" } }, { status: 501 });
  }
  if (session !== "demo") return NextResponse.json({ error: { code: "unauthorized", message: "演示会话无效" } }, { status: 401 });
  const { id } = await context.params;
  const body = await request.json().catch(() => ({}));
  if (body.status !== "已通过" && body.status !== "已驳回") {
    return NextResponse.json({ error: { code: "validation_error", message: "无效的审核状态" } }, { status: 400 });
  }
  const review = updateMockReview(id, body.status);
  if (!review) return NextResponse.json({ error: { code: "not_found", message: "审核项不存在" } }, { status: 404 });
  return NextResponse.json({ data: review });
}
