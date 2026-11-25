import { NextResponse } from "next/server";

/**
 * 微站留资 BFF：浏览器不直连后端，避免暴露内部地址与跨域配置。
 * 只透传联系方式与 URL 归因参数；来源合法性由后端按项目校验。
 */

function apiBase() {
  return process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
}

export async function POST(request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  const source = body as Record<string, unknown>;
  const clean = (value: unknown, max: number) => (typeof value === "string" ? value.trim().slice(0, max) : "");
  const payload = {
    contact_name: clean(source.contact_name, 64) || null,
    contact_phone: clean(source.contact_phone, 64) || null,
    contact_wechat: clean(source.contact_wechat, 64) || null,
    note: clean(source.note, 1000) || null,
    source_sample_id: clean(source.source_sample_id, 64) || null,
    source_question_id: clean(source.source_question_id, 64) || null,
    utm_campaign: clean(source.utm_campaign, 128) || null,
  };
  try {
    const response = await fetch(`${apiBase()}/api/v1/public/sites/${encodeURIComponent(slug)}/leads`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => null);
    return NextResponse.json(
      data ?? { error: { code: "site_unavailable", message: "提交服务返回异常" } },
      { status: response.status, headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { error: { code: "site_unavailable", message: "提交服务暂不可用，请稍后再试" } },
      { status: 503 },
    );
  }
}
