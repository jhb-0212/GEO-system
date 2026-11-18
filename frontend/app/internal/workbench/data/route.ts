import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const statsKinds = new Map([
  ["stats-overview", "overview"],
  ["stats-overview-by-answer-kind", "overview-by-answer-kind"],
  ["stats-by-engine", "by-engine"],
  ["stats-by-question", "by-question"],
  ["stats-engine-health", "engine-health"],
  ["stats-geo", "geo"],
  ["stats-sources", "sources"],
  ["stats-publish-visibility", "publish-visibility"],
]);

function failure(error: unknown) {
  if (error instanceof BackendError) {
    return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
  }
  return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
}

async function context(request: Request) {
  const token = await getSessionToken();
  if (!token || isMockMode() && token !== "demo") return { error: NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 }) };
  if (isMockMode()) return { error: NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用真实接口" } }, { status: 400 }) };
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  if (!uuid.test(projectId)) return { error: NextResponse.json({ error: { code: "validation_error", message: "请选择有效项目" } }, { status: 400 }) };
  return { token, projectId, url };
}

export async function GET(request: Request) {
  const ctx = await context(request);
  if ("error" in ctx) return ctx.error;
  const { token, projectId, url } = ctx;
  const kind = url.searchParams.get("kind");
  const page = Math.max(1, Number(url.searchParams.get("page")) || 1);
  const pageSize = Math.min(100, Math.max(1, Number(url.searchParams.get("page_size")) || 20));
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  const base = `/api/v1/projects/${projectId}` as const;
  try {
    if (kind === "brand-profile") {
      return NextResponse.json(await backendRequest(`${base}/brand-profile`, token));
    }
    if (kind === "diagnostics") {
      if (url.searchParams.get("failure_code")) params.set("failure_code", url.searchParams.get("failure_code")!);
      return NextResponse.json(await backendRequest(`${base}/monitoring/diagnostics?${params}` as `/api/v1/${string}`, token));
    }
    if (kind === "source-reviews") {
      if (url.searchParams.get("status")) params.set("status", url.searchParams.get("status")!);
      return NextResponse.json(await backendRequest(`${base}/citations/source-reviews?${params}` as `/api/v1/${string}`, token));
    }
    if (["rounds", "channels", "tasks", "questions", "keywords", "samples", "citations", "unknown-domains", "publish-tasks", "publish-accounts", "content-versions", "faqs", "materials", "audit-logs"].includes(kind ?? "")) {
      const path = kind === "rounds" ? `${base}/monitoring/rounds` : kind === "audit-logs" ? `${base}/audit-logs` : kind === "tasks" ? `${base}/monitoring/tasks` : kind === "questions" ? `${base}/questions` : kind === "keywords" ? `${base}/keywords` : kind === "samples" ? `${base}/monitoring/samples` : kind === "citations" ? `${base}/citations` : kind === "unknown-domains" ? `${base}/citations/unknown-domains` : kind === "publish-tasks" ? `${base}/publish/tasks` : kind === "publish-accounts" ? `${base}/publish/accounts` : kind === "content-versions" ? `${base}/content-versions` : kind === "faqs" ? `${base}/faqs` : kind === "materials" ? `${base}/materials` : `${base}/channels`;
      if (kind === "tasks" && url.searchParams.get("round_id")) params.set("round_id", url.searchParams.get("round_id")!);
      if (kind === "questions" && url.searchParams.get("status")) params.set("status", url.searchParams.get("status")!);
      if (kind === "questions" && url.searchParams.get("question_type")) params.set("question_type", url.searchParams.get("question_type")!);
      if (kind === "keywords" && url.searchParams.get("category")) params.set("category", url.searchParams.get("category")!);
      if (kind === "keywords" && url.searchParams.has("is_active")) params.set("is_active", url.searchParams.get("is_active")!);
      if (kind === "faqs" && url.searchParams.get("status")) params.set("status", url.searchParams.get("status")!);
      if (kind === "faqs" && url.searchParams.get("category")) params.set("category", url.searchParams.get("category")!);
      if (kind === "faqs" && url.searchParams.get("deleted")) params.set("deleted", url.searchParams.get("deleted")!);
      if (kind === "faqs" && url.searchParams.get("q")) params.set("q", url.searchParams.get("q")!);
      if (kind === "materials" && url.searchParams.get("category")) params.set("category", url.searchParams.get("category")!);
      if (["samples", "citations", "publish-tasks", "content-versions"].includes(kind ?? "") && url.searchParams.get("status")) {
        params.set(kind === "citations" ? "review_status" : "status", url.searchParams.get("status")!);
      }
      if (kind === "citations" && url.searchParams.get("sample_id")) params.set("sample_id", url.searchParams.get("sample_id")!);
      return NextResponse.json(await backendRequest(`${path}?${params}` as `/api/v1/${string}`, token));
    }
    if (kind === "trace") {
      const trace = (url.searchParams.get("trace_id") ?? "").trim();
      if (!/^[A-Za-z0-9_-]{4,64}$/.test(trace)) {
        return NextResponse.json({ error: { code: "validation_error", message: "trace_id 无效" } }, { status: 400 });
      }
      return NextResponse.json(await backendRequest(`${base}/monitoring/traces/${encodeURIComponent(trace)}`, token));
    }
    if (kind === "sample") {
      const id = url.searchParams.get("id") ?? "";
      if (!uuid.test(id)) return NextResponse.json({ error: { code: "validation_error", message: "样本 ID 无效" } }, { status: 400 });
      return NextResponse.json(await backendRequest(`${base}/monitoring/samples/${id}`, token));
    }
    if (kind === "content-version" || kind === "content-reviews" || kind === "content-links") {
      const id = url.searchParams.get("id") ?? "";
      if (!uuid.test(id)) return NextResponse.json({ error: { code: "validation_error", message: "内容版本 ID 无效" } }, { status: 400 });
      const suffix = kind === "content-reviews" ? `/reviews?${params}` : kind === "content-links" ? "/links" : "";
      return NextResponse.json(await backendRequest(`${base}/content-versions/${id}${suffix}`, token));
    }
    if (kind === "content-export") {
      const id = url.searchParams.get("id") ?? "";
      if (!uuid.test(id)) return NextResponse.json({ error: { code: "validation_error", message: "内容版本 ID 无效" } }, { status: 400 });
      return NextResponse.json(await backendRequest(`${base}/content-versions/${id}/export`, token));
    }
    if (kind === "question-versions") {
      const id = url.searchParams.get("id") ?? "";
      if (!uuid.test(id)) return NextResponse.json({ error: { code: "validation_error", message: "题目 ID 无效" } }, { status: 400 });
      return NextResponse.json(await backendRequest(`${base}/questions/${id}/versions?${params}`, token));
    }
    if (kind === "channel") {
      const id = url.searchParams.get("id") ?? "";
      if (!uuid.test(id)) return NextResponse.json({ error: { code: "validation_error", message: "渠道 ID 无效" } }, { status: 400 });
      return NextResponse.json(await backendRequest(`${base}/channels/${id}`, token));
    }
    if (kind === "faq-categories") {
      return NextResponse.json(await backendRequest(`${base}/faqs/categories` as `/api/v1/${string}`, token));
    }
    if (kind === "keyword-categories") {
      return NextResponse.json(await backendRequest(`${base}/keywords/categories` as `/api/v1/${string}`, token));
    }
    if (["competitors", "metric-definitions", "members", "plans", "quotes", "budget-approvals"].includes(kind ?? "")) {
      const path = kind === "competitors" ? `${base}/competitors` : kind === "metric-definitions" ? `${base}/metric-definitions` : kind === "members" ? `${base}/members` : kind === "plans" ? `${base}/plans` : kind === "quotes" ? `${base}/media-quotes` : `${base}/budget-approvals`;
      if (kind === "budget-approvals" && url.searchParams.get("status")) params.set("status", url.searchParams.get("status")!);
      if (kind === "budget-approvals" && url.searchParams.get("category")) params.set("category", url.searchParams.get("category")!);
      return NextResponse.json(await backendRequest(`${path}?${params}` as `/api/v1/${string}`, token));
    }
    if (kind === "member-candidates") {
      const q = url.searchParams.get("q") ?? "";
      const query = new URLSearchParams();
      if (q) query.set("q", q);
      return NextResponse.json(await backendRequest(`${base}/members/candidates?${query}` as `/api/v1/${string}`, token));
    }
    if (kind === "stats-monthly") {
      const query = new URLSearchParams();
      const month = url.searchParams.get("month");
      if (month) query.set("month", month);
      return NextResponse.json(await backendRequest(`${base}/stats/monthly?${query}` as `/api/v1/${string}`, token));
    }
    if (kind === "lead-funnel") {
      const query = new URLSearchParams();
      for (const key of ["start_date", "end_date"]) {
        const value = url.searchParams.get(key);
        if (value) query.set(key, value);
      }
      return NextResponse.json(await backendRequest(`${base}/leads/funnel?${query}` as `/api/v1/${string}`, token));
    }
    if (kind === "channels-export") {
      const api = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
      const response = await fetch(new URL(`${base}/channels/export`, api), { headers: { Authorization: `Bearer ${token}`, Accept: "text/csv" }, cache: "no-store" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        return NextResponse.json(payload?.error ? payload : { error: { code: "export_failed", message: "导出失败" } }, { status: response.status });
      }
      return new Response(response.body, { status: 200, headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "text/csv; charset=utf-8",
        "Content-Disposition": response.headers.get("Content-Disposition") ?? "attachment; filename=channels.csv",
        "Cache-Control": "no-store",
      } });
    }
    if (kind === "leads-export") {
      const api = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
      const response = await fetch(new URL(`${base}/leads/export`, api), { headers: { Authorization: `Bearer ${token}`, Accept: "text/csv" }, cache: "no-store" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        return NextResponse.json(payload?.error ? payload : { error: { code: "export_failed", message: "导出失败" } }, { status: response.status });
      }
      return new Response(response.body, { status: 200, headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "text/csv; charset=utf-8",
        "Content-Disposition": response.headers.get("Content-Disposition") ?? "attachment; filename=leads.csv",
        "Cache-Control": "no-store",
      } });
    }
    const stat = statsKinds.get(kind ?? "");
    if (stat || kind === "stats-export") {
      const filters = new URLSearchParams();
      for (const key of ["round_id", "engine_id", "question_id", "start_at", "end_at", "limit", "answer_kind", "question_type"]) {
        const value = url.searchParams.get(key);
        if (value) filters.set(key, value);
      }
      const path = `${base}/stats/${stat ?? "export"}?${filters}` as `/api/v1/${string}`;
      if (kind !== "stats-export") return NextResponse.json(await backendRequest(path, token));
      const api = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
      const response = await fetch(new URL(path, api), { headers: { Authorization: `Bearer ${token}`, Accept: "text/csv" }, cache: "no-store" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        return NextResponse.json(payload?.error ? payload : { error: { code: "export_failed", message: "导出失败" } }, { status: response.status });
      }
      return new Response(response.body, { status: 200, headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "text/csv; charset=utf-8",
        "Content-Disposition": response.headers.get("Content-Disposition") ?? "attachment; filename=stats.csv",
        "Cache-Control": "no-store",
      } });
    }
    return NextResponse.json({ error: { code: "unknown_kind", message: "不支持的数据类型" } }, { status: 400 });
  } catch (error) { return failure(error); }
}

export async function POST(request: Request) {
  const ctx = await context(request);
  if ("error" in ctx) return ctx.error;
  const { token, projectId, url } = ctx;
  const kind = url.searchParams.get("kind");
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  const base = `/api/v1/projects/${projectId}` as const;
  let path: `/api/v1/${string}`;
  if (kind === "rounds") path = `${base}/monitoring/rounds`;
  else if (kind === "project-confirm") path = `${base}/confirm`;
  else if (kind === "channels") path = `${base}/channels`;
  else if (kind === "questions") path = `${base}/questions`;
  else if (kind === "keywords") path = `${base}/keywords`;
  else if (kind === "faq") path = `${base}/faqs`;
  else if (kind === "faq-restore" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/faqs/${url.searchParams.get("id")}/restore`;
  else if (kind === "question-version" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/questions/${url.searchParams.get("id")}/versions`;
  else if (kind === "sample-review" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/monitoring/samples/${url.searchParams.get("id")}/manual-review`;
  else if (kind === "sample-resample" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/monitoring/samples/${url.searchParams.get("id")}/resample`;
  else if (kind === "sample-reanalyze" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/monitoring/samples/${url.searchParams.get("id")}/reanalyze`;
  else if (kind === "source-review-classify" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/citations/source-reviews/${url.searchParams.get("id")}/classify`;
  else if (kind === "stat-snapshot" && uuid.test(url.searchParams.get("round_id") ?? "")) path = `${base}/stats/snapshots?round_id=${url.searchParams.get("round_id")}`;
  else if (kind === "sample-create" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/monitoring/tasks/${url.searchParams.get("id")}/samples`;
  else if (kind === "content-status" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/content-versions/${url.searchParams.get("id")}/status`;
  else if (kind === "publish-task") path = `${base}/publish/tasks`;
  else if (kind === "publish-account") path = `${base}/publish/accounts`;
  else if (kind === "competitors") path = `${base}/competitors`;
  else if (kind === "metric-definitions") path = `${base}/metric-definitions`;
  else if (kind === "plans") path = `${base}/plans`;
  else if (kind === "quotes") path = `${base}/media-quotes`;
  else if (kind === "budget-approvals") path = `${base}/budget-approvals`;
  else if (kind === "budget-review" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/budget-approvals/${url.searchParams.get("id")}/review`;
  else if (kind === "members") path = `${base}/members`;
  else if (kind === "quote-review" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/media-quotes/${url.searchParams.get("id")}/review`;
  else if (kind === "content-item") path = `${base}/contents`;
  else if (kind === "content-version-create" && uuid.test(url.searchParams.get("id") ?? "")) path = `${base}/contents/${url.searchParams.get("id")}/versions`;
  else if (["content-submit", "content-review"].includes(kind ?? "") && uuid.test(url.searchParams.get("id") ?? "")) {
    path = `${base}/content-versions/${url.searchParams.get("id")}/${kind === "content-submit" ? "submit" : "review"}`;
  }
  else if (["publish-attempt", "publish-receipt", "publish-verify"].includes(kind ?? "") && uuid.test(url.searchParams.get("id") ?? "")) {
    const suffix = kind === "publish-attempt" ? "attempts" : kind === "publish-receipt" ? "receipts" : "verify";
    path = `${base}/publish/tasks/${url.searchParams.get("id")}/${suffix}`;
  }
  else if (kind === "batch" && uuid.test((body as { round_id?: string }).round_id ?? "")) path = `${base}/monitoring/rounds/${(body as { round_id: string }).round_id}/tasks/batch`;
  else if (kind === "publish-visibility-check") path = `${base}/stats/publish-visibility/check`;
  else return NextResponse.json({ error: { code: "validation_error", message: "操作或轮次无效" } }, { status: 400 });
  try { return NextResponse.json(await backendRequest(path, token, { method: "POST", ...(kind === "batch" ? {} : { body: JSON.stringify(body) }) }), { status: kind === "batch" || kind === "faq-restore" || kind === "publish-visibility-check" || kind === "project-confirm" || kind === "budget-review" || kind === "content-status" || kind === "sample-reanalyze" ? 200 : 201 }); }
  catch (error) { return failure(error); }
}

export async function PUT(request: Request) {
  const ctx = await context(request);
  if ("error" in ctx) return ctx.error;
  const { token, projectId, url } = ctx;
  const kind = url.searchParams.get("kind");
  const id = url.searchParams.get("id") ?? "";
  if (kind !== "brand-profile" && kind !== "content-links") return NextResponse.json({ error: { code: "validation_error", message: "操作无效" } }, { status: 400 });
  if (kind === "content-links" && !uuid.test(id)) return NextResponse.json({ error: { code: "validation_error", message: "内容版本 ID 无效" } }, { status: 400 });
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  const path = kind === "content-links" ? `/api/v1/projects/${projectId}/content-versions/${id}/links` : `/api/v1/projects/${projectId}/brand-profile`;
  try {
    return NextResponse.json(await backendRequest(path as `/api/v1/${string}`, token, { method: "PUT", body: JSON.stringify(body) }));
  } catch (error) { return failure(error); }
}

export async function PATCH(request: Request) {
  const ctx = await context(request);
  if ("error" in ctx) return ctx.error;
  const { token, projectId, url } = ctx;
  const id = url.searchParams.get("id") ?? "";
  const kind = url.searchParams.get("kind");
  if (!["channel", "question", "keyword", "citation", "faq", "material", "lead", "competitor", "metric-definition", "plan", "quote", "member"].includes(kind ?? "") || !uuid.test(id)) return NextResponse.json({ error: { code: "validation_error", message: "资源 ID 无效" } }, { status: 400 });
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  const resource = kind === "question" ? "questions" : kind === "keyword" ? "keywords" : kind === "citation" ? "citations" : kind === "faq" ? "faqs" : kind === "material" ? "materials" : kind === "lead" ? "leads" : kind === "competitor" ? "competitors" : kind === "metric-definition" ? "metric-definitions" : kind === "plan" ? "plans" : kind === "quote" ? "media-quotes" : kind === "member" ? "members" : "channels";
  try { return NextResponse.json(await backendRequest(`/api/v1/projects/${projectId}/${resource}/${id}`, token, { method: "PATCH", body: JSON.stringify(body) })); }
  catch (error) { return failure(error); }
}

export async function DELETE(request: Request) {
  const ctx = await context(request);
  if ("error" in ctx) return ctx.error;
  const { token, projectId, url } = ctx;
  const id = url.searchParams.get("id") ?? "";
  const kind = url.searchParams.get("kind");
  if (!["keyword", "faq", "member"].includes(kind ?? "") || !uuid.test(id)) {
    return NextResponse.json({ error: { code: "validation_error", message: "目标 ID 无效" } }, { status: 400 });
  }
  const resource = kind === "faq" ? "faqs" : kind === "member" ? "members" : "keywords";
  try { return NextResponse.json(await backendRequest(`/api/v1/projects/${projectId}/${resource}/${id}`, token, { method: "DELETE" })); }
  catch (error) { return failure(error); }
}
