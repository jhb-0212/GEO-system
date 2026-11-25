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

export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  if (isMockMode()) return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用知识库接口" } }, { status: 400 });

  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  const projectId = typeof body?.project_id === "string" ? body.project_id : "";
  const action = typeof body?.action === "string" ? body.action : "";
  if (!uuid.test(projectId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 });
  }

  const base = `/api/v1/projects/${projectId}/knowledge` as const;
  try {
    if (action === "parse") {
      const materialId = typeof body?.material_id === "string" ? body.material_id : "";
      if (!uuid.test(materialId)) {
        return NextResponse.json({ error: { code: "validation_error", message: "请选择有效素材" } }, { status: 400 });
      }
      return NextResponse.json(await backendRequest(`${base}/documents/${materialId}/parse` as `/api/v1/${string}`, token, { method: "POST" }));
    }
    if (action === "accept") {
      const candidateId = typeof body?.candidate_id === "string" ? body.candidate_id : "";
      if (!uuid.test(candidateId)) {
        return NextResponse.json({ error: { code: "validation_error", message: "请选择有效候选事实" } }, { status: 400 });
      }
      const payload = {
        fact_type: body?.fact_type,
        fact_key: body?.fact_key,
        fact_value: body?.fact_value,
        change_note: body?.change_note,
      };
      return NextResponse.json(await backendRequest(`${base}/candidate-facts/${candidateId}/accept` as `/api/v1/${string}`, token, {
        method: "POST", body: JSON.stringify(payload),
      }));
    }
    if (action === "reject") {
      const candidateId = typeof body?.candidate_id === "string" ? body.candidate_id : "";
      if (!uuid.test(candidateId)) {
        return NextResponse.json({ error: { code: "validation_error", message: "请选择有效候选事实" } }, { status: 400 });
      }
      return NextResponse.json(await backendRequest(`${base}/candidate-facts/${candidateId}/reject` as `/api/v1/${string}`, token, {
        method: "POST", body: JSON.stringify({ note: body?.note }),
      }));
    }
    return NextResponse.json({ error: { code: "validation_error", message: "未知知识库操作" } }, { status: 400 });
  } catch (error) {
    return failure(error);
  }
}
