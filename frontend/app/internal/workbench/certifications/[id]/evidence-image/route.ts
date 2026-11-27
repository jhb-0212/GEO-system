import { NextResponse } from "next/server";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

async function resolve(context: { params: Promise<{ id: string }> }, request: Request) {
  const session = await getSessionToken();
  if (!session) return { error: NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 }) };
  if (isMockMode()) return { error: NextResponse.json({ error: { code: "mock_only", message: "演示模式不读写真实资质" } }, { status: 400 }) };
  const { id } = await context.params;
  if (!uuid.test(id)) return { error: NextResponse.json({ error: { code: "validation_error", message: "资质 ID 无效" } }, { status: 400 }) };
  const projectId = new URL(request.url).searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) return { error: NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 }) };
  return { session, id, projectId, url: new URL(`/api/v1/projects/${projectId}/certifications/${id}/evidence-image`, apiBase()) };
}

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const resolved = await resolve(context, request);
  if ("error" in resolved) return resolved.error;
  try {
    const response = await fetch(resolved.url, {
      headers: { Authorization: `Bearer ${resolved.session}` },
      cache: "no-store",
    });
    if (!response.ok) return new NextResponse(null, { status: response.status });
    const body = await response.arrayBuffer();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "Content-Type": response.headers.get("content-type") ?? "image/png",
        "Content-Disposition": response.headers.get("content-disposition") ?? "inline",
        "Cache-Control": "private, max-age=300",
      },
    });
  } catch {
    return new NextResponse(null, { status: 503 });
  }
}

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const resolved = await resolve(context, request);
  if ("error" in resolved) return resolved.error;
  try {
    const incoming = await request.formData();
    const response = await fetch(resolved.url, {
      method: "POST",
      headers: { Authorization: `Bearer ${resolved.session}` },
      body: incoming,
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "certification_image_failed", message: "证据图片上传失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}

export async function DELETE(request: Request, context: { params: Promise<{ id: string }> }) {
  const resolved = await resolve(context, request);
  if ("error" in resolved) return resolved.error;
  try {
    const response = await fetch(resolved.url, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${resolved.session}` },
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return NextResponse.json(payload ?? { error: { code: "certification_image_failed", message: "证据图片删除失败" } }, { status: response.status });
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
  }
}
