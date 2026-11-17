import type { ApiEnvelope, ApiErrorEnvelope } from "./types";

export class BackendError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

// Only server routes import this file. The browser always calls the same-origin frontend API.
export async function backendRequest<T>(
  path: `/api/v1/${string}`,
  token: string,
  init: RequestInit = {},
): Promise<ApiEnvelope<T>> {
  const base = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
  const response = await fetch(new URL(path, base), {
    ...init,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  });

  const payload: ApiEnvelope<T> | ApiErrorEnvelope = await response.json().catch(() => null);
  if (!response.ok) {
    // 网关/未捕获异常可能返回 HTML 或空体；不能把真实状态码吞成 invalid_response。
    // 只有当 error 字段确实是 { code, message } 形状时才透传，否则一律按 HTTP 状态兜底，
    // 避免 {"error": null} / {"error": "boom"} 这类简化错误体触发 TypeError。
    const upstream = payload && typeof payload === "object" && "error" in payload ? payload.error : null;
    const error = upstream && typeof upstream === "object" && typeof upstream.code === "string" && typeof upstream.message === "string"
      ? upstream
      : {
          code: `upstream_http_${response.status}`,
          message: response.status >= 500
            ? `后端接口异常（HTTP ${response.status}），响应不是 JSON`
            : `后端请求失败（HTTP ${response.status}），响应不是 JSON`,
        };
    throw new BackendError(response.status, error.code, error.message);
  }
  if (!payload || typeof payload !== "object") {
    throw new BackendError(502, "invalid_response", "后端响应格式不正确");
  }
  if ("error" in payload) {
    throw new BackendError(502, payload.error.code, payload.error.message);
  }
  if (!("data" in payload)) {
    throw new BackendError(502, "invalid_response", "后端响应缺少 data 字段");
  }
  return payload;
}
