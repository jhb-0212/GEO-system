import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";
import { addMockLead } from "@/lib/workbench/mock";
import type { Lead } from "@/lib/workbench/types";

export async function POST(request: Request) {
  const session = await getSessionToken();
  if (!session) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });

  const body = await request.json().catch(() => ({}));
  const input: Pick<Lead, "contactName" | "phone" | "interest" | "source" | "projectId"> = {
    contactName: typeof body.contactName === "string" ? body.contactName.trim() : "",
    phone: typeof body.phone === "string" ? body.phone.trim() : "",
    interest: typeof body.interest === "string" ? body.interest.trim() : "",
    source: typeof body.source === "string" ? body.source.trim() : "",
    projectId: typeof body.projectId === "string" ? body.projectId : "",
  };
  if (!input.contactName || !input.projectId) {
    return NextResponse.json({ error: { code: "validation_error", message: "请填写联系人并选择项目" } }, { status: 400 });
  }

  if (isMockMode()) {
    if (session !== "demo") return NextResponse.json({ error: { code: "unauthorized", message: "演示会话无效" } }, { status: 401 });
    return NextResponse.json({ data: addMockLead(input) }, { status: 201 });
  }

  try {
    const response = await backendRequest<{ id: string }>(`/api/v1/projects/${input.projectId}/leads`, session, {
      method: "POST",
      body: JSON.stringify({
        contact_name: input.contactName,
        contact_phone: input.phone || null,
        interested_course: input.interest || null,
        lead_source: input.source || null,
      }),
    });
    return NextResponse.json({ data: { ...input, id: response.data.id, status: "待跟进", createdAt: "刚刚" } }, { status: 201 });
  } catch (error) {
    if (error instanceof BackendError) return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
